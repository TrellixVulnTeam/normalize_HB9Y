from datetime import datetime, timezone
from apispec import APISpec
from apispec_webframeworks.flask import FlaskPlugin
from flask import Flask
from flask import make_response, send_file
from flask_executor import Executor
from flask_cors import CORS
from os import path, getenv, stat

from . import db
from .forms import NormalizeForm
from .logging import getLoggers
import json

from .utils import mkdir, get_tmp_dir, validate_form, create_ticket, save_to_temp, check_directory_writable, \
    get_temp_dir, get_geodataframe, normalize_gdf, store_gdf


class OutputDirNotSet(Exception):
    pass


if getenv('OUTPUT_DIR') is None:
    raise OutputDirNotSet('Environment variable OUTPUT_DIR is not set.')

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
    ticket, gdf, resource_type, file_name, success, comment = future.result()
    if gdf is not None:
        rel_path = datetime.now().strftime("%y%m%d")
        rel_path = path.join(rel_path, ticket)
        output_path: str = path.join(getenv('OUTPUT_DIR'), rel_path)
        mkdir(output_path)
        filepath = store_gdf(gdf, resource_type, file_name, output_path)
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
        gdf = get_geodataframe(form, src_path)
        gdf = normalize_gdf(form, gdf)
        file_name = path.split(src_path)[1].split('.')[0] + '_normalized'
    except Exception as e:
        mainLogger.error(f'Processing of ticket: {ticket} failed')
        return ticket, None, None, None, 0, str(e)
    else:
        return ticket, gdf, form.resource_type.data, file_name, 1, None


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
    tmp_dir: str = get_tmp_dir("normalize")
    ticket: str = create_ticket()
    src_path: str = path.join(tmp_dir, 'src', ticket)
    src_file_path: str = save_to_temp(form, src_path)

    # Immediate results
    if form.response.data == "prompt":
        gdf = get_geodataframe(form, src_file_path)
        gdf = normalize_gdf(form, gdf)
        file_name = path.split(src_file_path)[1].split('.')[0] + '_normalized'
        output_file = store_gdf(gdf, form.resource_type.data, file_name, src_path)
        file_content = open(output_file, 'rb')
        return send_file(file_content, attachment_filename=path.basename(output_file), as_attachment=True)
    # Wait for results
    else:
        enqueue.submit(ticket, src_file_path, form)
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
