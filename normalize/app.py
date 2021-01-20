from typing import Union
from datetime import datetime, timezone
from apispec import APISpec
from apispec_webframeworks.flask import FlaskPlugin
from flask import Flask
from flask import make_response, send_file, abort
from flask_executor import Executor
from flask_cors import CORS
from os import path, getenv, stat

import geopandas as gpd
import pandas as pd
from shapely import wkt
from werkzeug.utils import secure_filename

from . import db
from .forms import NormalizeForm
from .logging import getLoggers
import json

from .normalization_functions import transliteration, phone_normalization, special_character_normalization, \
    alphabetical_normalization, case_normalization, date_normalization, value_cleaning, wkt_normalization, \
    column_name_normalization
from .utils import mkdir, get_tmp_dir, validate_form, create_ticket, save_to_temp, check_directory_writable, \
    get_temp_dir, get_delimiter


if getenv('OUTPUT_DIR') is None:
    raise Exception('Environment variable OUTPUT_DIR is not set.')


# Logging
mainLogger, accountLogger = getLoggers()

# OpenAPI documentation
spec = APISpec(
    title="Normalize API",
    version=getenv('VERSION'),
    info=dict(
        description="A simple service to Normalize spatial files",
        contact={"email": "kpsarakis94@gmail.com"}
    ),
    externalDocs={"description": "GitHub", "url": "https://github.com/OpertusMundi/normalize"},
    openapi_version="3.0.2",
    plugins=[FlaskPlugin()],
)

app = Flask(__name__, instance_relative_config=True, instance_path=getenv('INSTANCE_PATH'))
environment = getenv('FLASK_ENV')
if environment == 'testing' or environment == 'development':
    secret_key = environment
else:
    secret_key = getenv('SECRET_KEY') or open(getenv('SECRET_KEY_FILE')).read()
app.config.from_mapping(
    SECRET_KEY=secret_key,
    DATABASE=getenv('DATABASE'),
)


def executor_callback(future):
    """The callback function called when a job has completed."""
    ticket, result, success, comment = future.result()
    if result is not None:
        rel_path = datetime.now().strftime("%y%m%d")
        rel_path = path.join(rel_path, ticket)
        mkdir(path.join(getenv('OUTPUT_DIR'), rel_path))
        filepath = path.join(getenv('OUTPUT_DIR'), rel_path, "output.csv")
        result.to_file(filepath)
    else:
        filepath = None
    with app.app_context():
        dbc = db.get_db()
        db_result = dbc.execute('SELECT requested_time, filesize FROM tickets WHERE ticket = ?;', [ticket]).fetchone()
        time = db_result['requested_time']
        filesize = db_result['filesize']
        execution_time = round((datetime.now(timezone.utc) - time.replace(tzinfo=timezone.utc)).total_seconds(), 3)
        dbc.execute('UPDATE tickets SET result=?, success=?, status=1, execution_time=?, comment=? WHERE ticket=?;',
                    [filepath, success, execution_time, comment, ticket])
        dbc.commit()
        accountLogger(ticket=ticket, success=success, execution_start=time, execution_time=execution_time,
                      comment=comment, filesize=filesize)
        dbc.close()

# Ensure the instance folder exists and initialize application, db and executor.
mkdir(app.instance_path)
db.init_app(app)
executor = Executor(app)
executor.add_default_done_callback(executor_callback)

# Enable CORS
if getenv('CORS') is not None:
    if getenv('CORS')[0:1] == '[':
        origins = json.loads(getenv('CORS'))
    else:
        origins = getenv('CORS')
    cors = CORS(app, origins=origins)


@executor.job
def enqueue(ticket: str, src_path: str, form: NormalizeForm) -> tuple:
    """Enqueue a profile job (in case requested response type is 'deferred')."""
    filesize = stat(src_path).st_size
    dbc = db.get_db()
    dbc.execute('INSERT INTO tickets (ticket, filesize) VALUES(?, ?);', [ticket, filesize])
    dbc.commit()
    dbc.close()
    try:
        gdf: Union[pd.Dataframe, gpd.GeoDataFrame] = None
        if form.resource_type.data == "csv":
            df = pd.read_csv(src_path, delimiter=get_delimiter(src_path))
            df['wkt'] = df['wkt'].apply(wkt.loads)
            gdf = gpd.GeoDataFrame(df)
        if form.date_normalization.data:
            for column in form.date_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: date_normalization(x))
        if form.phone_normalization.data:
            for column in form.phone_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: phone_normalization(x))
        if form.special_character_normalization.data:
            for column in form.special_character_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: special_character_normalization(x))
        if form.alphabetical_normalization.data:
            for column in form.alphabetical_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: alphabetical_normalization(x))
        if form.case_normalization.data:
            for column in form.case_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: case_normalization(x))
        if form.transliteration.data:
            if form.transliteration_langs and form.transliteration_lang != '':
                langs = form.transliteration_langs + [form.transliteration_lang]
            elif form.transliteration_langs:
                langs = form.transliteration_langs
            elif form.transliteration_lang != '':
                langs = form.transliteration_lang
            else:
                abort(400, 'You selected the transliteration option without specifing the sources language(s)')
            for column in form.transliteration.data:
                gdf[column] = gdf[column].apply(lambda x: transliteration(x, langs))
        if form.value_cleaning.data:
            for column in form.value_cleaning.data:
                gdf[column] = gdf[column].apply(lambda x: value_cleaning(x))
        if form.wkt_normalization.data:
            for column in form.wkt_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: wkt_normalization(x))
        if form.column_name_normalization.data:
            gdf.columns = column_name_normalization(list(gdf.columns))
    except Exception as e:
        return ticket, None, 0, str(e)
    else:
        return ticket, gdf, 1, None


@app.route("/")
def index():
    """The index route, gives info about the API endpoints."""
    mainLogger.info('Generating OpenAPI document...')
    return make_response(spec.to_dict(), 200)


@app.route("/_health")
def health_check():
    """Perform basic health checks
    ---
    get:
      tags:
      - Health
      summary: Get health status
      description: 'Get health status'
      operationId: 'getHealth'
      responses:
        default:
          description: An object with status information
          content:
            application/json:
              schema:
                type: object
                properties:
                  status:
                    type: string
                    description: A status of 'OK' or 'FAILED'
                  reason:
                    type: string
                    description: the reason of failure (if failed)
                  detail:
                    type: string
                    description: more details on this failure (if failed)
              examples:
                example-1:
                  value: |-
                    {"status": "OK"}
    """
    mainLogger.info('Performing health checks...')
    # Check that temp directory is writable
    try:
        check_directory_writable(get_temp_dir())
    except Exception as exc:
        return make_response({'status': 'FAILED', 'reason': 'temp directory not writable', 'detail': str(exc)},
                             200)
    # Check that we can connect to our PostGIS backend
    try:
        dbc = db.get_db()
        dbc.execute('SELECT 1').fetchone()
    except Exception as exc:
        return make_response({'status': 'FAILED', 'reason': 'cannot connect to SQLite backend', 'detail': str(exc)},
                             200)
    # Check that we can connect to our Geoserver backend
    # Todo ...
    return make_response({'status': 'OK'},
                         200)


@app.route("/normalize", methods=["POST"])
def normalize():
    """Normalize"""
    form = NormalizeForm()
    validate_form(form, mainLogger)
    print(form.response.data)
    print(form.transliteration.data)
    print(form.resource.data.filename)
    tmp_dir: str = get_tmp_dir("normalize")
    ticket: str = create_ticket()
    src_file_path: str = save_to_temp(form, tmp_dir, ticket)
    # Immediate results
    if form.response.data == "prompt":
        gdf: Union[pd.Dataframe, gpd.GeoDataFrame] = None
        if form.resource_type.data == "csv":
            df = pd.read_csv(src_file_path, delimiter=get_delimiter(src_file_path))
            df['wkt'] = df['wkt'].apply(wkt.loads)
            gdf = gpd.GeoDataFrame(df)
        if form.date_normalization.data:
            for column in form.date_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: date_normalization(x))
        if form.phone_normalization.data:
            for column in form.phone_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: phone_normalization(x))
        if form.special_character_normalization.data:
            for column in form.special_character_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: special_character_normalization(x))
        if form.alphabetical_normalization.data:
            for column in form.alphabetical_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: alphabetical_normalization(x))
        if form.case_normalization.data:
            for column in form.case_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: case_normalization(x))
        if form.transliteration.data:
            if form.transliteration_langs and form.transliteration_lang != '':
                langs = form.transliteration_langs + [form.transliteration_lang]
            elif form.transliteration_langs:
                langs = form.transliteration_langs
            elif form.transliteration_lang != '':
                langs = form.transliteration_lang
            else:
                abort(400, 'You selected the transliteration option without specifing the sources language(s)')
            for column in form.transliteration.data:
                gdf[column] = gdf[column].apply(lambda x: transliteration(x, langs))
        if form.value_cleaning.data:
            for column in form.value_cleaning.data:
                gdf[column] = gdf[column].apply(lambda x: value_cleaning(x))
        if form.wkt_normalization.data:
            for column in form.wkt_normalization.data:
                gdf[column] = gdf[column].apply(lambda x: wkt_normalization(x))
        if form.column_name_normalization.data:
            gdf.columns = column_name_normalization(list(gdf.columns))
        src_path = path.join(tmp_dir, 'src', ticket)
        mkdir(src_path)
        filename = secure_filename('output.csv')
        src_file = path.join(src_path, filename)
        gdf.to_csv(src_file)
        file_content = open(src_file, 'rb')
        return send_file(file_content, attachment_filename=path.basename(src_file), as_attachment=True,
                         mimetype='application/tar+gzip')
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, file_type="netcdf")
        response = {"ticket": ticket, "endpoint": f"/resource/{ticket}", "status": f"/status/{ticket}"}
        return make_response(response, 202)


@app.route("/status/<ticket>")
def status(ticket):
    """Get the status of a specific ticket.
    ---
    get:
      summary: Get the status of a normalize request.
      operationId: getStatus
      description: Returns the status of a request corresponding to a specific ticket.
      tags:
        - Status
      parameters:
        - name: ticket
          in: path
          description: The ticket of the request
          required: true
          schema:
            type: string
      responses:
        200:
          description: Ticket found and status returned.
          content:
            application/json:
              schema:
                type: object
                properties:
                  completed:
                    type: boolean
                    description: Whether normalization process has been completed or not.
                  success:
                    type: boolean
                    description: Whether normalization process completed succesfully.
                  comment:
                    type: string
                    description: If normalization has failed, a short comment describing the reason.
                  requested:
                    type: string
                    format: datetime
                    description: The timestamp of the request.
                  executionTime:
                    type: integer
                    description: The execution time in seconds.
        404:
          description: Ticket not found.
    """
    if ticket is None:
        return make_response('Ticket is missing.', 400)
    dbc = db.get_db()
    results = dbc.execute('SELECT status, success, requested_time, execution_time, comment FROM tickets WHERE ticket = ?', [ticket]).fetchone()
    if results is not None:
        if results['success'] is not None:
            success = bool(results['success'])
        else:
            success = None
        return make_response({"completed": bool(results['status']), "success": success,
                              "requested": results['requested_time'].isoformat(),
                              "executionTime": results['execution_time'], "comment": results['comment']}, 200)
    return make_response('Not found.', 404)


@app.route("/resource/<ticket>")
def resource(ticket):
    """Get the resulted resource associated with a specific ticket.
    ---
    get:
      summary: Get the resource associated to a normalize request.
      description: Returns the resource resulted from a normalize request corresponding to a specific ticket.
      tags:
        - Resource
      parameters:
        - name: ticket
          in: path
          description: The ticket of the request
          required: true
          schema:
            type: string
      responses:
        200:
          description: The normalized compressed spatial file.
          content:
            application/x-tar:
              schema:
                type: string
                format: binary
        404:
          description: Ticket not found or normalize has not been completed.
        507:
          description: Resource does not exist.
    """
    if ticket is None:
        return make_response('Resource ticket is missing.', 400)
    dbc = db.get_db()
    rel_path = dbc.execute('SELECT result FROM tickets WHERE ticket = ?', [ticket]).fetchone()
    if rel_path is None:
        return make_response('Not found.', 404)
    file = path.join(getenv('OUTPUT_DIR'), rel_path['result'])
    if not path.isfile(file):
        return make_response('Resource does not exist.', 507)
    file_content = open(file, 'rb')
    return send_file(file_content, attachment_filename=path.basename(file), as_attachment=True, mimetype='application/tar+gzip')


with app.test_request_context():
    spec.path(view=normalize)
    spec.path(view=status)
    spec.path(view=resource)
