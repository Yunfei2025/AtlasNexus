import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from settings.paths import DIR_INPUT
from web.tabs.market.data import _select_on_the_run_bonds, _load_on_the_run_bonds

tenors = ['1Y','2Y','5Y','10Y','20Y','30Y']
print('DIR_INPUT', DIR_INPUT)
print('TBond size', (DIR_INPUT / 'TBond-InstrumentInfo.pkl').stat().st_size)
print('CBond size', (DIR_INPUT / 'CBond-InstrumentInfo.pkl').stat().st_size)
print('TBond picks', _select_on_the_run_bonds('TBond', tenors))
print('CBond picks', _select_on_the_run_bonds('CBond', tenors))
print('OTR table:')
print(_load_on_the_run_bonds().to_string(index=False))
