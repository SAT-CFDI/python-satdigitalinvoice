from typing import Sequence

# Errors for the console 2.1
class ConsoleErrors(Exception):
    def __init__(self, *args, errors: Sequence[str]):
        super().__init__(*args)
        self.errors = errors
