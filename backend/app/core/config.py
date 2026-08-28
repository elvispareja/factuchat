"""Configuración central. Todos los secretos vienen del entorno (.env fuera del repo, OWASP A02)."""

from decimal import Decimal
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"  # development | test | production
    debug: bool = False

    # Base de datos: la app se conecta con el rol factuchat_app (sujeto a RLS).
    database_url: str = Field(
        default="postgresql+psycopg://factuchat_app:app@localhost:5432/factuchat"
    )
    # Migraciones y seeds corren con el rol propietario (nunca expuesto a la app).
    database_url_admin: str = Field(
        default="postgresql+psycopg://factuchat:admin@localhost:5432/factuchat"
    )

    redis_url: str = "redis://localhost:6379/0"

    # JWT — sesiones cortas (30 min) + refresh con rotación (fase 1.3)
    secret_key: str = Field(default="dev-only-cambia-esto")
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    jwt_algorithm: str = "HS256"

    # Clave AES-256-GCM (base64, 32 bytes) para cifrar secretos TOTP en reposo (OWASP A04)
    totp_enc_key: str = Field(default="")
    # Clave maestra AES-256-GCM para los .p12 y sus contraseñas (fase 2.2).
    # Vive SOLO en el entorno; el descifrado ocurre en memoria del worker al firmar.
    cert_enc_key: str = Field(default="")

    # Rate limiting de login: 5 intentos / 15 min por IP y por cuenta (fase 1.3)
    login_max_attempts: int = 5
    login_window_seconds: int = 900

    sentry_dsn: str = ""
    cors_origins: list[str] = ["http://localhost:5173"]

    # Dominio definitivo (factuchat.ai o factuchat.ec) — PENDIENTE de confirmación
    # del dueño del producto; nada debe hardcodear el dominio.
    app_domain: str = ""

    # --- Datos públicos de contacto y cobro (fase 6.2) ---
    # Viven aquí y no en el bundle del frontend: el dominio sigue sin confirmarse
    # y las cuentas bancarias son datos del negocio, no del código.
    contacto_email: str = ""  # vacío ⇒ info@{dominio_publico}
    contacto_email_ventas: str = ""  # vacío ⇒ ventas@{dominio_publico}
    contacto_telefono: str = "099 337 1891"
    contacto_telefono_e164: str = "+593993371891"
    contacto_direccion: str = "Quito: sector “El Batán”, Portete E12-97 y José de Abascal."
    contacto_maps_url: str = "https://maps.app.goo.gl/JYQvEgUQ6y7RjBh58"
    # Unificado: la maqueta se contradecía (agenda "L–S 07:00–21:00" vs
    # confirmación "L–D 09:00–19:00"). Manda la agenda, que es la que salta los
    # domingos y ofrece de 07:00 a 21:00.
    contacto_horario: str = "Lunes a sábado, de 07:00 a 21:00."
    cobro_titular: str = "Libio Elvis Pareja Paredes"
    cobro_titular_identificacion: str = "092373715-9"
    # "Banco|número" — cuentas de ahorros donde se recibe la transferencia
    cobro_cuentas: list[str] = [
        "Banco Pichincha|2203135848",
        "Banco Guayaquil|14919843",
        "Banco del Pacífico|1049939424",
        "Produbanco|20059861108",
        "Coop. JEP|406163101400",
    ]

    # --- Motor de emisión SRI (fase 2) ---
    sri_recepcion_url_pruebas: str = (
        "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline"
    )
    sri_autorizacion_url_pruebas: str = (
        "https://celcer.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline"
    )
    sri_recepcion_url_produccion: str = (
        "https://cel.sri.gob.ec/comprobantes-electronicos-ws/RecepcionComprobantesOffline"
    )
    sri_autorizacion_url_produccion: str = (
        "https://cel.sri.gob.ec/comprobantes-electronicos-ws/AutorizacionComprobantesOffline"
    )
    sri_timeout_seconds: int = 30

    # --- WhatsApp Cloud API de Meta (fase 5) ---
    wa_app_secret: str = ""  # firma el X-Hub-Signature-256 de cada webhook
    wa_verify_token: str = ""  # el que Meta devuelve al verificar la suscripción
    wa_access_token: str = ""  # token permanente del número
    wa_phone_number_id: str = ""
    wa_api_version: str = "v21.0"
    wa_timeout_seconds: int = 20
    # Tope mensual de gasto en conversaciones; 0 = sin tope configurado
    wa_presupuesto_mensual: Decimal = Decimal("0")
    # Se avisa cuando la proyección del mes supera este % del presupuesto
    wa_alerta_pct: int = 80

    # Archivos generados (XML firmados, RIDE) — volumen del worker/api
    storage_dir: str = "var/storage"

    # Correo saliente. Sin SMTP configurado, los correos se escriben como .eml
    # en email_outbox_dir (modo desarrollo/tests).
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    # STARTTLS (587) abre en claro y sube a TLS; el 465 va cifrado desde el
    # primer byte y NO admite STARTTLS. Confundirlos deja el envío colgado hasta
    # el timeout, así que el puerto 465 fuerza el modo correcto por su cuenta.
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    email_from: str = ""
    email_outbox_dir: str = "var/outbox"

    # --- Buzón SRI (fase 7) ---
    # Interruptor GLOBAL del módulo. Nace apagado, igual que en la maqueta: con
    # el flag apagado los correos se siguen registrando para depurar, pero el
    # cliente no ve nada y su saldo de retenciones NO se toca.
    buzon_activo: bool = False
    # Dominio de las direcciones {ruc}@… Vacío ⇒ se deriva del dominio público.
    buzon_dominio: str = ""
    # Clave propia, distinta de CERT_ENC_KEY: el radio de daño de la firma
    # electrónica no debe ampliarse a los documentos del buzón, y cada una se
    # rota por su cuenta. 32 bytes en base64.
    buzon_enc_key: str = ""
    # Firma del webhook de correo entrante (HMAC-SHA256 sobre el cuerpo crudo).
    # Sin este secreto el webhook rechaza todo: nunca falla abierto.
    buzon_webhook_secret: str = ""
    # Recolección por IMAP, alternativa al webhook para despliegue propio.
    buzon_imap_host: str = ""
    buzon_imap_port: int = 993
    buzon_imap_user: str = ""
    buzon_imap_password: str = ""
    buzon_imap_carpeta: str = "INBOX"
    # Un correo con adjuntos no debería pesar más que esto
    buzon_max_bytes: int = 15 * 1024 * 1024
    # Días sin recibir nada tras los cuales se le recuerda al inquilino que
    # configure el reenvío desde el SRI (la maqueta fija 30)
    buzon_dias_alerta: int = 30

    @property
    def smtp_tls_implicito(self) -> bool:
        """El 465 es TLS implícito aunque nadie lo declare."""
        return self.smtp_ssl or self.smtp_port == 465

    @property
    def dominio_buzon(self) -> str:
        return self.buzon_dominio or self.dominio_publico

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def dominio_publico(self) -> str:
        """El dominio que se muestra al público. Mientras APP_DOMAIN no esté
        definido se usa factuchat.ec —el del pie de la maqueta— para que la web
        y los correos no salgan con el dominio en blanco. En producción
        APP_DOMAIN es obligatorio, así que este respaldo no llega allí."""
        return self.app_domain or "factuchat.ec"

    @property
    def email_ventas(self) -> str:
        return self.contacto_email_ventas or f"ventas@{self.dominio_publico}"

    @property
    def email_info(self) -> str:
        return self.contacto_email or f"info@{self.dominio_publico}"

    @model_validator(mode="after")
    def sin_valores_inseguros_en_produccion(self) -> "Settings":
        """En producción no se arranca con defaults de desarrollo (OWASP A02/A07)."""
        if self.is_production:
            if len(self.secret_key) < 32 or self.secret_key.startswith("dev-"):
                raise ValueError("SECRET_KEY de producción inválida (mínimo 32 caracteres)")
            if not self.totp_enc_key:
                raise ValueError("TOTP_ENC_KEY es obligatoria en producción")
            if not self.cert_enc_key:
                raise ValueError("CERT_ENC_KEY es obligatoria en producción")
            # Sin el secreto de la app no se puede verificar la firma de Meta, y
            # un webhook sin verificar acepta órdenes de cualquiera (OWASP A08)
            if self.wa_access_token and not self.wa_app_secret:
                raise ValueError("WA_APP_SECRET es obligatoria si WhatsApp está activo")
            if self.debug:
                raise ValueError("DEBUG debe estar apagado en producción")
            # El dominio aparece en la web, en los correos y en los enlaces que
            # se le mandan al cliente: adivinarlo en producción no es aceptable.
            if not self.app_domain:
                raise ValueError("APP_DOMAIN es obligatorio en producción")
            # El buzón guarda documentos fiscales de terceros: encenderlo sin
            # clave de cifrado los dejaría en claro en el disco (OWASP A04).
            if self.buzon_activo and not self.buzon_enc_key:
                raise ValueError("BUZON_ENC_KEY es obligatoria si BUZON_ACTIVO está encendido")
            # Un webhook de correo sin firma acepta documentos de cualquiera, y
            # esos documentos alteran la declaración de impuestos del cliente.
            if self.buzon_activo and not (self.buzon_webhook_secret or self.buzon_imap_host):
                raise ValueError(
                    "Con BUZON_ACTIVO hay que configurar BUZON_WEBHOOK_SECRET o BUZON_IMAP_HOST"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
