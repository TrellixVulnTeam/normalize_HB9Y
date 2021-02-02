import csv
import tarfile
import zipfile
import os
from tempfile import gettempdir, mkstemp
from uuid import uuid4
from os import path, makedirs, getenv
from flask import abort
from flask_wtf import FlaskForm
from werkzeug.utils import secure_filename
import geovaex

from normalize.normalization_functions import date_normalization, column_name_normalization, \
    value_cleaning, transliteration, case_normalization, alphabetical_normalization, special_character_normalization, \
    phone_normalization


def validate_form(form: FlaskForm, logger) -> None:
    if not form.validate_on_submit():
        logger.error(f'Error while parsing input parameters: {str(form.errors)}')
        abort(400, form.errors)


def create_ticket() -> str:
    ticket = str(uuid4())
    return ticket


def get_subdirectories(folder_path: str) -> list:
    subdirectories = []
    entry: os.DirEntry
    for entry in os.scandir(folder_path):
        if not entry.name.startswith('.') and entry.is_dir():
            subdirectories.append(entry.name)
    return subdirectories


def get_extracted_path(folder_path: str):
    extracted_path = folder_path
    subdirectories = get_subdirectories(folder_path)
    if len(subdirectories) == 0:
        return extracted_path
    else:
        return get_extracted_path(path.join(extracted_path, subdirectories[0]))


def uncompress_file(src_file: str) -> str:
    """Checks whether the file is compressed and uncompresses it"""
    if not path.isdir(src_file):
        src_path = path.dirname(src_file)
        if tarfile.is_tarfile(src_file):
            with tarfile.open(src_file, 'r') as handle:
                handle.extractall(src_path)
                extracted_path = get_extracted_path(src_path)
                return extracted_path
        elif zipfile.is_zipfile(src_file):
            with zipfile.ZipFile(src_file, 'r') as handle:
                handle.extractall(src_path)
                extracted_path = get_extracted_path(src_path)
                return extracted_path
    return src_file


def mkdir(folder_path: str) -> None:
    """Creates recursively the path, ignoring warnings for existing directories."""
    try:
        makedirs(folder_path)
    except OSError:
        pass


def get_tmp_dir(namespace: str) -> str:
    tempdir = getenv('TEMPDIR') or gettempdir()
    tempdir = path.join(tempdir, namespace)
    mkdir(tempdir)
    return tempdir


def save_to_temp(form: FlaskForm, src_path: str) -> str:
    mkdir(src_path)
    filename = secure_filename(form.resource.data.filename)
    src_file = path.join(src_path, filename)
    form.resource.data.save(src_file)
    return src_file


def get_temp_dir():
    """Return the temporary directory"""
    return getenv('TEMPDIR') or gettempdir()


def check_directory_writable(d):
    fd, file_name = mkstemp(None, None, d)
    os.unlink(file_name)


def get_delimiter(ds_path: str) -> str:
    """ Returns the delimiter of the csv file """
    with open(ds_path) as f:
        first_line = f.readline()
        s = csv.Sniffer()
        return str(s.sniff(first_line).delimiter)


def make_zip(zip_name, path_to_zip):
    zip_handle = zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED)
    os.chdir(path_to_zip)
    for root, dirs, files in os.walk('.'):
        for file in files:
            zip_handle.write(os.path.join(root, file))


def get_geodataframe(form: FlaskForm, src_file_path: str):
    try:
        if form.resource_type.data == "csv":
            csv_file_path = src_file_path.split('.')[0]
            file_name = csv_file_path + '.arrow'
            if form.csv_delimiter.data:
                delimiter = form.csv_delimiter.data
            else:
                delimiter = get_delimiter(src_file_path)
            if form.crs.data:
                crs = form.crs.data
            else:
                crs = 'WGS 84'
            geovaex.io.to_arrow(src_file_path, file_name, crs=crs, delimiter=delimiter, null_values=[" "])
            gdf = geovaex.open(file_name)
        elif form.resource_type.data == "shp":
            shp_file_path = uncompress_file(src_file_path)
            file_name = shp_file_path + '.arrow'
            geovaex.io.to_arrow(shp_file_path, file_name)
            gdf = geovaex.open(file_name)
        else:
            gdf = None
            abort(400, "Not supported file type, the supported ones are csv and shp")
    except TypeError:
        abort(400, "Error while reading the file")
    else:
        return gdf


def perform_date_normalization(form, gdf):
    if form.date_normalization.data:
        for column in form.date_normalization.data:
            gdf[column] = gdf[column].apply(lambda x: date_normalization(x))
    return gdf


def perform_phone_normalization(form, gdf):
    if form.phone_normalization.data:
        for column in form.phone_normalization.data:
            gdf[column] = gdf[column].apply(lambda x: phone_normalization(x))
    return gdf


def perform_special_character_normalization(form, gdf):
    if form.special_character_normalization.data:
        for column in form.special_character_normalization.data:
            gdf[column] = gdf[column].apply(lambda x: special_character_normalization(x))
    return gdf


def perform_alphabetical_normalization(form, gdf):
    if form.alphabetical_normalization.data:
        for column in form.alphabetical_normalization.data:
            gdf[column] = gdf[column].apply(lambda x: alphabetical_normalization(x))
    return gdf


def perform_case_normalization(form, gdf):
    if form.case_normalization.data:
        for column in form.case_normalization.data:
            gdf[column] = gdf[column].apply(lambda x: case_normalization(x))
    return gdf


def perform_transliteration(form, gdf):
    if form.transliteration.data:
        if form.transliteration_langs.data and form.transliteration_lang.data != '':
            langs = form.transliteration_langs.data + [form.transliteration_lang.data]
        elif form.transliteration_langs.data:
            langs = form.transliteration_langs.data
        elif form.transliteration_lang.data != '':
            langs = form.transliteration_lang.data
        else:
            abort(400, 'You selected the transliteration option without specifying the sources language(s)')
        for column in form.transliteration.data:
            gdf[column] = gdf[column].apply(lambda x: transliteration(x, langs))
    return gdf


def perform_value_cleaning(form, gdf):
    if form.value_cleaning.data:
        for column in form.value_cleaning.data:
            gdf[column] = gdf[column].apply(lambda x: value_cleaning(x))
    return gdf


def perform_wkt_normalization(form, gdf):
    if form.wkt_normalization.data:
        gdf.constructive.make_valid(inplace=True)
        gdf.constructive.normalize(inplace=True)
    return gdf


def perform_column_name_normalization(form, gdf):
    if form.column_name_normalization.data:
        gdf.columns = column_name_normalization(list(gdf.columns))
    return gdf


def normalize_gdf(form, gdf):
    gdf = perform_date_normalization(form, gdf)
    gdf = perform_phone_normalization(form, gdf)
    gdf = perform_special_character_normalization(form, gdf)
    gdf = perform_alphabetical_normalization(form, gdf)
    gdf = perform_case_normalization(form, gdf)
    gdf = perform_transliteration(form, gdf)
    gdf = perform_value_cleaning(form, gdf)
    gdf = perform_wkt_normalization(form, gdf)
    gdf = perform_column_name_normalization(form, gdf)
    return gdf


def store_gdf(gdf, resource_type, file_name, src_path) -> str:
    mkdir(src_path)
    if resource_type == "csv":
        stored_path = os.path.join(src_path, file_name + '.csv')
        gdf.export(stored_path)
        return stored_path
    elif resource_type == "shp":
        output_dir = os.path.join(src_path, file_name)
        mkdir(output_dir)
        gdf.export(os.path.join(output_dir, file_name + '.shp'), driver="ESRI ShapeFile")
        stored_path = os.path.join(output_dir + '.zip')
        make_zip(stored_path, output_dir)
        return stored_path
    else:
        abort(400, "Not supported file type, the supported ones are csv and shp")
