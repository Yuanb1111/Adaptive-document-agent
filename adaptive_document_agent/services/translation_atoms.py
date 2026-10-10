"""Protect literal quantities from rescaling while localizing their labels."""
import re

from .display_copy_tokens import display_text


def protect_quantities(text: str, language: str) -> tuple[str, dict[str, str]]:
    from .executive_brief import _MONEY_QUANTITY
    chinese = bool(re.search(r'(?i)中文|chinese|^zh(?:-|$)', language))
    atoms = {}
    def replace(match):
        literal = match[0]
        # Only explicit monetary quantities get deterministic unit wording.
        # Bare counts/percentages remain model copy and are numerically checked.
        if not (match['prefix'] or match['suffix']) or not match['unit']:
            return literal
        token = f'⟦Q{len(atoms)}⟧'
        if token in text:
            raise ValueError('Source copy collides with a protected translation token')
        value = literal
        if chinese:
            from .brief_table_evidence import canonical_quantity
            currency, _, unit = canonical_quantity(match['prefix'] or match['suffix'], match['value'], match['unit'])
            unit = {'million': '百万元', 'thousand': '千元', 'billion': '十亿元',
                    'trillion': '万亿元'}.get(unit)
            currency = {'rmb': '人民币', 'usd': '美元', 'us$': '美元', 'hkd': '港元',
                        'hk$': '港元', 'eur': '欧元', '€': '欧元'}.get(currency)
            if currency and unit:
                # Preserve coefficient, comma/decimal spelling and the exact
                # source sign/parentheses. No currency or scale conversion.
                value = (currency + (match['open'] or '') + (match['sign'] or '')
                         + match['value'] + unit + (')' if match['open'] else ''))
        atoms[token] = value
        return token
    return _MONEY_QUANTITY.sub(replace, display_text(text)), atoms


def restore_quantities(text: str, atoms: dict[str, str]) -> str:
    tokens = re.findall(r'⟦Q\d+⟧', text)
    if set(tokens) != set(atoms) or any(tokens.count(token) != 1 for token in atoms):
        raise ValueError('Translation changed a protected quantity token')
    for token, literal in atoms.items():
        text = text.replace(token, literal)
    return text
