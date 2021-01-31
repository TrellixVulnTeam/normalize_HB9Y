from flask_wtf import FlaskForm
from wtforms import FileField, StringField, FieldList
from wtforms.validators import DataRequired, AnyOf, Optional


class NormalizeForm(FlaskForm):
    resource = FileField('resource', validators=[DataRequired()])
    resource_type = StringField('resource_type', validators=[DataRequired(),
                                                             AnyOf(['csv', 'shp'],
                                                                   "Permitted values for resource_type are csv or shp")])
    csv_delimiter = StringField('csv_delimiter', validators=[Optional()])
    crs = StringField('crs', validators=[Optional()])
    response = StringField('response',
                           validators=[Optional(),
                                       AnyOf(['prompt', 'deferred'],
                                             "Permitted values for response are prompt or deferred")], default='prompt')

    date_normalization = FieldList(StringField('date_normalization', validators=[Optional()], default=[]),
                                   min_entries=0, validators=[Optional()])
    phone_normalization = FieldList(StringField('phone_normalization', validators=[Optional()], default=[]),
                                    min_entries=0, validators=[Optional()])
    special_character_normalization = FieldList(StringField('special_character_normalization', validators=[Optional()], default=[]),
                                                min_entries=0, validators=[Optional()])
    alphabetical_normalization = FieldList(StringField('alphabetical_normalization', validators=[Optional()], default=[]),
                                           min_entries=0, validators=[Optional()])
    case_normalization = FieldList(StringField('case_normalization', validators=[Optional()], default=[]),
                                   min_entries=0, validators=[Optional()])
    transliteration = FieldList(StringField('transliteration', validators=[Optional()], default=[]),
                                min_entries=0, validators=[Optional()])
    transliteration_langs = FieldList(StringField('transliteration_langs', validators=[Optional()], default=[]),
                                      min_entries=0, validators=[Optional()])
    transliteration_lang = StringField('transliteration_lang', validators=[Optional()], default='')
    value_cleaning = FieldList(StringField('value_cleaning', validators=[Optional()], default=[]),
                               min_entries=0, validators=[Optional()])
    wkt_normalization = FieldList(StringField('wkt_normalization', validators=[Optional()], default=[]),
                                  min_entries=0, validators=[Optional()])
    column_name_normalization = FieldList(StringField('column_name_normalization', validators=[Optional()], default=[]),
                                          min_entries=0, validators=[Optional()])

    class Meta:
        csrf = False
