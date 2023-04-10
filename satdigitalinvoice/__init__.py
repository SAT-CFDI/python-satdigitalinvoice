import logging
import os

import PySimpleGUI as sg

SOURCE_DIRECTORY = os.path.dirname(__file__)
DATA_DIRECTORY = ".data"
PPD = "PPD"
PUE = "PUE"


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

    def __init__(self, debug=False):
        # set up logging
        if debug:
            logging.basicConfig(level=logging.ERROR)
        add_file_handler()

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
                    background_color=sg.theme_background_color(),  # '#a0dbd9',
                    no_scrollbar=True,
                    border_width=0,
                    write_only=True,
                    disabled=True,
                )
            ]
        ]

        self.window = sg.Window(
            f"Facturación Masiva CFDI 4.0",  # {self.csd_signer.rfc}
            layout,
            size=(640, 480),
            resizable=True,
            font=("Courier New", 10, "bold"),
            no_titlebar=True,
            modal=True,
            background_color=sg.theme_background_color(),
            auto_close=True,
            auto_close_duration=6,  # seconds
        )

    @staticmethod
    def read_config():
        from satdigitalinvoice.file_data_managers import ConfigManager
        return ConfigManager()

    def run(self):
        self.window.finalize()
        self.window.read(timeout=0)

        try:
            from satdigitalinvoice.facturacion import FacturacionGUI
            config = self.read_config()
            app = FacturacionGUI(config)
        except Exception as ex:
            logging.exception(ex)
            self.window['console'].update(
                str(ex)
            )
            self.window.read()
            self.window.close()
            return

        self.window.close()
        app.run()
