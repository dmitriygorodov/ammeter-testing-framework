from Ammeters.base_ammeter import AmmeterEmulatorBase
from src.utils.Utils import generate_random_float


class EntesAmmeter(AmmeterEmulatorBase):
    DEFAULT_COMMAND = b'MEASURE_ENTES -get_data'

    def measure_current(self) -> float:
        magnetic_field = generate_random_float(0.01, 0.1)  # Magnetic field strength (0.01T - 0.1T)
        calibration_factor = generate_random_float(500, 2000)  # Calibration factor (500 - 2000)
        current = magnetic_field * calibration_factor
        return current
