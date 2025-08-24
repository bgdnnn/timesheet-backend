from datetime import date

def week_monday(d: date) -> date:
    return d if d.weekday() == 0 else d.fromordinal(d.toordinal() - d.weekday())
