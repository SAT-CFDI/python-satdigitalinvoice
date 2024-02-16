import logging
import os
from zipfile import ZipFile

import PySimpleGUI as sg

SOURCE_DIRECTORY = os.path.dirname(__file__)

DATA_DIRECTORY = ".data"
ARCHIVOS_DIRECTORY = "archivos"
METADATA_FILE = os.path.join(ARCHIVOS_DIRECTORY, "metadata.csv")
TEMPLATES_DIRECTORY = "templates"
TEMP_DIRECTORY = ".data/temp"


def add_file_handler():
    os.makedirs(DATA_DIRECTORY, exist_ok=True)
    fh = logging.FileHandler(
        os.path.join(DATA_DIRECTORY, 'errors.log'),
        mode='a',
        encoding='utf-8',
    )
    fh.setLevel(logging.ERROR)
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    fh.setFormatter(formatter)
    logging.root.addHandler(fh)


class FacturacionLauncher:
    def __init__(self):
        # sg.theme('Reddit')
        add_file_handler()

        # layout
        layout = [
            [sg.Column([[
                sg.Image(source=os.path.join(SOURCE_DIRECTORY, "images", "logo.png"), pad=2),
            ]], justification='center', pad=0, background_color='black')],
            [
                sg.Multiline(
                    "Cargando Aplicación...",
                    expand_x=True,
                    expand_y=True,
                    key="console",
                    background_color='#a0dbd9',
                    no_scrollbar=True,
                    border_width=0,
                    write_only=True,
                    disabled=True,
                )
            ]
        ]

        self.window = sg.Window(
            f"Facturación Masiva CFDI 4.0",
            layout,
            size=(640, 480),
            resizable=True,
            font=("Courier New", 11, "bold"),
            no_titlebar=True,
            modal=True,
            background_color='#a0dbd9',  # sg.theme_background_color(),
            auto_close=True,
            auto_close_duration=10,  # seconds
        )

    @staticmethod
    def read_config():
        from satdigitalinvoice.file_data_managers import ConfigManager
        return ConfigManager()

    # def add_sample_files(self):
    #     # loading the sample.zip
    #     try:
    #         with ZipFile(os.path.join(self.app_dir, 'sample.zip'), 'r') as zf:
    #             for member in zf.infolist():
    #                 if not os.path.exists(member.filename):
    #                     zf.extract(member)
    #     except FileNotFoundError:
    #         pass

    def run(self):
        self.window.finalize()
        self.window.read(timeout=0)

        try:
            # check if another directory is configured
            from satdigitalinvoice.file_data_managers import InitManager
            if cwd := InitManager().get('cwd'):
                os.chdir(cwd)
            # self.add_sample_files()

            from satdigitalinvoice.facturacion import FacturacionGUI
            app = FacturacionGUI(
                config=self.read_config()
            )
        except Exception as ex:
            logging.exception(ex)
            self.window['console'].update(
                f"Error al cargar la aplicación. {ex.__class__.__name__}: {ex}",
                text_color='red4',
            )
            self.window.read(close=True)
            return

        self.window.close()
        app.run()
