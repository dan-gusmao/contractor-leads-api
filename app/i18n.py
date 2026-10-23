"""English and Finnish message catalogue.

Errors are raised with a stable ``code``; the response carries both the
code (for clients) and a message in the caller's language.
"""

from fastapi import Request

SUPPORTED_LANGUAGES = ("en", "fi")
DEFAULT_LANGUAGE = "en"

MESSAGES: dict[str, dict[str, str]] = {
    "auth.invalid_credentials": {
        "en": "Invalid email or password.",
        "fi": "Virheellinen sähköposti tai salasana.",
    },
    "auth.not_authenticated": {
        "en": "Authentication required.",
        "fi": "Kirjautuminen vaaditaan.",
    },
    "auth.invalid_token": {
        "en": "Invalid or expired token.",
        "fi": "Virheellinen tai vanhentunut tunniste.",
    },
    "auth.suspended": {
        "en": "This account has been suspended.",
        "fi": "Tämä tili on jäädytetty.",
    },
    "auth.forbidden": {
        "en": "You do not have permission to do this.",
        "fi": "Sinulla ei ole oikeutta tähän toimintoon.",
    },
    "auth.email_taken": {
        "en": "An account with this email already exists.",
        "fi": "Tällä sähköpostilla on jo tili.",
    },
    "validation.invalid_business_id": {
        "en": "Y-tunnus must be in the format 1234567-8 with a valid check digit.",
        "fi": "Y-tunnuksen muoto on 1234567-8 ja tarkistusmerkin on oltava oikein.",
    },
    "validation.invalid_category": {
        "en": "Unknown project category: {category}.",
        "fi": "Tuntematon projektikategoria: {category}.",
    },
    "validation.invalid_budget": {
        "en": "Minimum budget cannot be greater than maximum budget.",
        "fi": "Vähimmäisbudjetti ei voi olla suurempi kuin enimmäisbudjetti.",
    },
    "validation.invalid_amount": {
        "en": "Amount must not be zero.",
        "fi": "Määrä ei voi olla nolla.",
    },
    "profile.exists": {
        "en": "A profile already exists for this account.",
        "fi": "Tälle tilille on jo luotu profiili.",
    },
    "profile.missing": {
        "en": "Create your profile first.",
        "fi": "Luo ensin profiilisi.",
    },
    "user.not_found": {
        "en": "User not found.",
        "fi": "Käyttäjää ei löytynyt.",
    },
    "contractor.not_found": {
        "en": "Contractor not found.",
        "fi": "Urakoitsijaa ei löytynyt.",
    },
    "project.not_found": {
        "en": "Project not found.",
        "fi": "Projektia ei löytynyt.",
    },
    "project.invalid_transition": {
        "en": "A project with status '{status}' cannot be {action}.",
        "fi": "Projektia, jonka tila on '{status}', ei voi {action}.",
    },
    "project.not_editable": {
        "en": "A project with status '{status}' cannot be edited.",
        "fi": "Projektia, jonka tila on '{status}', ei voi muokata.",
    },
    "project.not_public": {
        "en": "This project is not open for contractors.",
        "fi": "Tämä projekti ei ole avoinna urakoitsijoille.",
    },
    "image.too_many": {
        "en": "A project can have at most {limit} images.",
        "fi": "Projektilla voi olla enintään {limit} kuvaa.",
    },
    "image.invalid_type": {
        "en": "Only JPEG, PNG and WebP images are allowed.",
        "fi": "Vain JPEG-, PNG- ja WebP-kuvat ovat sallittuja.",
    },
    "image.too_large": {
        "en": "Image is larger than the allowed {limit} bytes.",
        "fi": "Kuva on suurempi kuin sallittu {limit} tavua.",
    },
    "image.not_found": {
        "en": "Image not found.",
        "fi": "Kuvaa ei löytynyt.",
    },
    "credits.insufficient": {
        "en": "Not enough credits. Required {required}, available {available}.",
        "fi": "Krediittejä ei ole tarpeeksi. Tarvitaan {required}, saatavilla {available}.",
    },
    "credits.negative_balance": {
        "en": "Adjustment would make the balance negative.",
        "fi": "Muutos tekisi saldosta negatiivisen.",
    },
    "credits.own_project": {
        "en": "You cannot unlock your own project.",
        "fi": "Et voi avata omaa projektiasi.",
    },
    "payment.unknown_package": {
        "en": "Unknown credit package: {package_id}.",
        "fi": "Tuntematon krediittipaketti: {package_id}.",
    },
    "payment.invalid_signature": {
        "en": "Invalid payment notification signature.",
        "fi": "Maksuilmoituksen allekirjoitus on virheellinen.",
    },
    "payment.not_found": {
        "en": "Payment not found.",
        "fi": "Maksua ei löytynyt.",
    },
    "message.not_allowed": {
        "en": "You can message about a project only after the contractor has unlocked it.",
        "fi": "Voit lähettää viestejä projektista vasta, kun urakoitsija on avannut sen.",
    },
    "conversation.not_found": {
        "en": "Conversation not found.",
        "fi": "Keskustelua ei löytynyt.",
    },
    "review.not_allowed": {
        "en": "You can review a contractor only after they unlocked one of your projects.",
        "fi": "Voit arvioida urakoitsijan vasta, kun hän on avannut jonkin projekteistasi.",
    },
    "review.exists": {
        "en": "You have already reviewed this contractor for this project.",
        "fi": "Olet jo arvioinut tämän urakoitsijan tästä projektista.",
    },
    "review.not_found": {
        "en": "Review not found.",
        "fi": "Arviota ei löytynyt.",
    },
}


def resolve_language(request: Request) -> str:
    """Pick a language from ``?lang=`` first, then ``Accept-Language``."""
    lang = request.query_params.get("lang")
    if lang in SUPPORTED_LANGUAGES:
        return lang
    header = request.headers.get("accept-language", "")
    for part in header.split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in SUPPORTED_LANGUAGES:
            return code
    return DEFAULT_LANGUAGE


def translate(code: str, lang: str, **params) -> str:
    entry = MESSAGES.get(code)
    if entry is None:
        return code
    template = entry.get(lang) or entry[DEFAULT_LANGUAGE]
    return template.format(**params)


class AppError(Exception):
    """A domain error rendered as ``{"error": {"code", "message"}}``."""

    def __init__(self, status_code: int, code: str, **params):
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.params = params
