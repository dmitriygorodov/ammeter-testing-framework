# Ammeters/Acme_Ammeter.py

from Ammeters.base_ammeter import AmmeterEmulatorBase
from src.utils.Utils import generate_random_float


class AcmeAmmeter(AmmeterEmulatorBase):
    DEFAULT_COMMAND = b"READ_CURRENT"

    def measure_current(self) -> float:
        return generate_random_float(0.0, 10.0)