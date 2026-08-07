from Ammeters.base_ammeter import AmmeterEmulatorBase
from src.utils.Utils import generate_random_float


class CircutorAmmeter(AmmeterEmulatorBase):
    DEFAULT_COMMAND = b'MEASURE_CIRCUTOR -get_measurement'

    def measure_current(self) -> float:
        num_samples = 10
        time_step = generate_random_float(0.001, 0.01)  # Time step (0.001s - 0.01s)
        voltages = [generate_random_float(0.1, 1.0) for _ in range(num_samples)]  # Voltage values

        current = sum(v * time_step for v in voltages)
        return current
