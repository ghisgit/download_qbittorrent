from dataclasses import dataclass


@dataclass
class Settings:
    verbose: bool = False
    debug_save: bool = False


settings = Settings()
