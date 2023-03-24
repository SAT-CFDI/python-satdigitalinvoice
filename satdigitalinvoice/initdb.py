import os

import diskcache

WORKING_DIR = 'working_dir'


class InitDB(diskcache.Cache):
    def __init__(self, base_path: str):
        super().__init__(directory=os.path.join(base_path, 'init'))
        self.base_path = base_path

    def set_cwd(self):
        cwd = self.get('working_dir', os.getcwd())
        os.chdir(cwd)

    def update_cwd(self, cwd):
        self['working_dir'] = cwd
        self.set_cwd()
