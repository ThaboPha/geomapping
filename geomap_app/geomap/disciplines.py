"""Selection helpers that retain the live discipline code and category."""
from .data import CATEGORIES


def provider_categories(disciplines):
    live = set(disciplines.ProviderCategory.dropna().astype(str))
    return list(CATEGORIES) + sorted(category for category in live if category and category not in CATEGORIES)


def discipline_label(code, disciplines):
    if code is None:
        return 'Any discipline'
    selected = disciplines.loc[disciplines.PracType == code, 'PracTypeDescr']
    name = str(selected.iloc[0]) if len(selected) else 'Unknown discipline'
    return f'{int(code):02d} — {name}'
