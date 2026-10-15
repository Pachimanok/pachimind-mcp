"""Public MCP input contracts; the API independently validates every command."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')

class Birthday(Input):
    mes: int = Field(ge=1, le=12)
    dia: int = Field(ge=1, le=31)
    anio: int | None = Field(default=None, ge=1900, le=2100)
    @model_validator(mode='after')
    def valid_date(self):
        from datetime import date
        date(self.anio or 2000, self.mes, self.dia)
        return self

class GeneralFact(Input):
    texto: str = Field(min_length=1, max_length=2000)
    categoria: Literal['interes', 'preferencia', 'familia', 'evento', 'salud', 'otro'] = 'otro'
    fecha: str | None = None
    vigente_hasta: str | None = None
    estado: Literal['vigente', 'pendiente', 'finalizado'] = 'vigente'
    @field_validator('fecha', 'vigente_hasta')
    @classmethod
    def exact_date(cls, value):
        if value is not None:
            from datetime import date
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError('Usá fecha YYYY-MM-DD')
        return value
    @model_validator(mode='after')
    def ordered_dates(self):
        if self.fecha and self.vigente_hasta and self.vigente_hasta < self.fecha:
            raise ValueError('Vigencia anterior a la fecha')
        return self

class PersonChanges(Input):
    nombre: str | None = Field(default=None, min_length=1, max_length=200)
    aliases: list[str] | None = None
    organizacion: str | None = None
    funcion: str | None = None
    relacion_conmigo: str | None = None
    ambitos: list[Literal['Trabajo', 'Apostólico', 'Colegios', 'Formación']] | None = None
    contactos_profesionales: dict[Literal['email_profesional', 'telefono_profesional', 'perfil_profesional'], str] | None = None
    redes_sociales: dict[Literal['linkedin', 'instagram', 'facebook', 'x', 'web', 'otra'], str] | None = None
    cumpleanos: Birthday | None = None
    datos_generales: list[GeneralFact] | None = None
    notas_manuales: str | None = None
    tipo: Literal['persona', 'idea', 'recurso', 'nota'] | None = None

class PersonEvidence(Input):
    field: str
    source_id: str
    quote: str = Field(min_length=1, max_length=4000)

class NoteLink(Input):
    target_id: str
    target_revision: str
    relation: Literal['participó en', 'mencionado en', 'trabaja con', 'vinculado al proyecto', 'fuente', 'relacionado con', 'referencia']
    action: Literal['add', 'remove'] = 'add'
    evidence: PersonEvidence | None = None

class ReservedSegment(Input):
    source_reference: str
    start_seconds: int = Field(ge=0)
    end_seconds: int = Field(ge=0)
