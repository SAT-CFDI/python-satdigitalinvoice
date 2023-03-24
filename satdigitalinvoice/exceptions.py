from typing import Sequence


class ConsoleErrors(Exception):
    def __init__(self, *args, errors: Sequence[str]):
        super().__init__(*args)
        self.errors = errors
