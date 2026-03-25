import os
from dotenv import load_dotenv


_ALL_PROVIDERS = ('circlek', 'neste', 'virsi', 'viada')
_DEFAULT_CREDIT_MESSAGE = '☕ Ja noderēja, kafijai. Ja ne, nu neko: buymeacoffee.com/pizzadesk'

class Config:
    def __init__(self, env_path: str | None = None):
        load_dotenv(dotenv_path=env_path)
        self.TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
        self.TARGET_URL = os.getenv('TARGET_URL', 'https://www.circlek.lv/degviela-miles/degvielas-cenas')
        self.ENABLED_PROVIDERS = self._parse_enabled_providers(os.getenv('ENABLED_PROVIDERS'))
        self.CREDIT_MESSAGE = self._parse_credit_message(os.getenv('CREDIT_MESSAGE'))

        if not self.TELEGRAM_TOKEN:
            raise ValueError('TELEGRAM_TOKEN must be set in .env file')

    @staticmethod
    def _parse_enabled_providers(raw_value: str | None) -> tuple[str, ...]:
        if not raw_value:
            return _ALL_PROVIDERS

        providers = tuple(
            item.strip().lower()
            for item in raw_value.split(',')
            if item.strip()
        )
        invalid = sorted(set(providers) - set(_ALL_PROVIDERS))
        if invalid:
            raise ValueError(
                'ENABLED_PROVIDERS contains unsupported values: '
                + ', '.join(invalid)
            )

        if not providers:
            raise ValueError('ENABLED_PROVIDERS must contain at least one provider')

        seen: list[str] = []
        for provider in providers:
            if provider not in seen:
                seen.append(provider)
        return tuple(seen)

    @staticmethod
    def _parse_credit_message(raw_value: str | None) -> str:
        if raw_value is None:
            return _DEFAULT_CREDIT_MESSAGE
        return raw_value.strip()
