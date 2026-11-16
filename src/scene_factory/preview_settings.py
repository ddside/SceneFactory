"""Preview lighting only; never a simulation environment or USD light contract."""
from .spec import fields,number

def validate_lighting(value):
    fields(value,'preview lighting',('preset','world_strength','sun_energy'))
    if value['preset']!='daytime':raise ValueError('unsupported preview lighting preset')
    number(value['world_strength'],'world strength',0,3);number(value['sun_energy'],'sun energy',0,10)
    return value
