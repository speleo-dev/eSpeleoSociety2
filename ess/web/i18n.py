"""Texts of the public verification pages in Slovak, English, French and Spanish (R55).

All languages are rendered into the page and switched in the browser: reloading the eCP page would use the
one-time QR token again. The default comes from the browser's Accept-Language header.
"""

LANGS = ("sk", "en", "fr", "es")
FLAGS = {"sk": "🇸🇰", "en": "🇬🇧", "fr": "🇫🇷", "es": "🇪🇸"}

TEXTS: dict[str, tuple[str, str, str, str]] = {  # key: (sk, en, fr, es)
    "ecp_title": ("Overenie eCP", "eCP verification", "Vérification de l'eCP", "Verificación del eCP"),
    "card_title": ("Overenie kartičky SSS", "SSS card verification", "Vérification de la carte SSS",
                   "Verificación de la tarjeta SSS"),
    "valid": ("✔ Člen Slovenskej speleologickej spoločnosti – jaskyniar",
              "✔ Member of the Slovak Speleological Society – caver",
              "✔ Membre de la Société spéléologique slovaque – spéléologue",
              "✔ Miembro de la Sociedad Espeleológica Eslovaca – espeleólogo"),
    "member": ("✔ Člen Slovenskej speleologickej spoločnosti", "✔ Member of the Slovak Speleological Society",
               "✔ Membre de la Société spéléologique slovaque", "✔ Miembro de la Sociedad Espeleológica Eslovaca"),
    "checked": ("Overené", "Verified", "Vérifié le", "Verificado el"),
    "suspended": ("⚠ Členstvo je pozastavené", "⚠ Membership is suspended", "⚠ L'adhésion est suspendue",
                  "⚠ La afiliación está suspendida"),
    "suspended_note": ("Preukaz momentálne neplatí.", "The card is currently not valid.",
                       "La carte n'est actuellement pas valide.", "El carné no es válido en este momento."),
    "not_member": ("✖ Nie je členom Slovenskej speleologickej spoločnosti",
                   "✖ Not a member of the Slovak Speleological Society",
                   "✖ N'est pas membre de la Société spéléologique slovaque",
                   "✖ No es miembro de la Sociedad Espeleológica Eslovaca"),
    "revoked": ("Tento preukaz bol zrušený.", "This card has been revoked.", "Cette carte a été révoquée.",
                "Este carné ha sido revocado."),
    "used": ("✖ Tento QR kód už bol použitý", "✖ This QR code has already been used",
             "✖ Ce code QR a déjà été utilisé", "✖ Este código QR ya ha sido utilizado"),
    "used_note": ("Požiadajte držiteľa, aby otvoril preukaz v Peňaženke Google znova – zobrazí sa nový kód.",
                  "Ask the holder to open the card in Google Wallet again – a new code will be shown.",
                  "Demandez au titulaire de rouvrir la carte dans Google Wallet : un nouveau code s'affichera.",
                  "Pida al titular que vuelva a abrir el carné en Google Wallet: se mostrará un código nuevo."),
    "invalid": ("✖ Preukaz sa nepodarilo overiť", "✖ The card could not be verified",
                "✖ La carte n'a pas pu être vérifiée", "✖ No se ha podido verificar el carné"),
    "invalid_note": ("Neplatný alebo neznámy kód.", "Invalid or unknown code.", "Code invalide ou inconnu.",
                     "Código no válido o desconocido."),
    "name": ("Meno", "Name", "Nom", "Nombre"),
    "address": ("Bydlisko", "Address", "Adresse", "Domicilio"),
    "club": ("Skupina", "Caving club", "Club", "Club"),
    "member_since": ("Člen SSS od", "SSS member since", "Membre de la SSS depuis", "Miembro de la SSS desde"),
    "fee": ("Členské", "Membership fee", "Cotisation", "Cuota de socio"),
    "paid_until": ("zaplatené do", "paid until", "payée jusqu'au", "pagada hasta el"),
    "unpaid": ("nezaplatené", "not paid", "non payée", "no pagada"),
    "compare": ("Porovnajte fotku s držiteľom preukazu.", "Compare the photo with the card holder.",
                "Comparez la photo avec le titulaire de la carte.", "Compare la foto con el titular del carné."),
    "contacts": ("Kontakty", "Contacts", "Contacts", "Contactos"),
    "club_chair": ("Predseda skupiny", "Club chair", "Président du club", "Presidente del club"),
    "sss_chair": ("Predseda SSS", "President of the SSS", "Président de la SSS", "Presidente de la SSS"),
    "documents": ("Dokumenty SSS", "SSS documents", "Documents de la SSS", "Documentos de la SSS"),
    "valid_until": ("platné do", "valid until", "valable jusqu'au", "válido hasta el"),
    "fee_paid_year": ("Členské zaplatené na rok", "Membership fee paid for", "Cotisation payée pour l'année",
                      "Cuota de socio pagada para el año"),
    "card_other_year": ("⚠ Kartička platí na rok", "⚠ The card is valid for", "⚠ La carte est valable pour l'année",
                        "⚠ La tarjeta es válida para el año"),
    "card_other_year_note": ("Na aktuálny rok nie je vydaná.", "It has not been issued for the current year.",
                             "Elle n'a pas été délivrée pour l'année en cours.",
                             "No se ha emitido para el año en curso."),
    "card_lost": ("✖ Kartička bola nahlásená ako stratená", "✖ The card has been reported lost",
                  "✖ La carte a été déclarée perdue", "✖ La tarjeta ha sido declarada perdida"),
    "card_stolen": ("✖ Kartička bola nahlásená ako ukradnutá", "✖ The card has been reported stolen",
                    "✖ La carte a été déclarée volée", "✖ La tarjeta ha sido declarada robada"),
    "card_lost_note": ("Kartička neplatí. Držiteľ nemusí byť jej majiteľom.",
                       "The card is not valid. The holder may not be its owner.",
                       "La carte n'est pas valide. Le porteur n'en est peut-être pas le titulaire.",
                       "La tarjeta no es válida. Es posible que el portador no sea su titular."),
    "card_replaced": ("✖ Kartička bola nahradená novou", "✖ The card has been replaced by a new one",
                      "✖ La carte a été remplacée par une nouvelle", "✖ La tarjeta ha sido sustituida por una nueva"),
    "card_replaced_note": ("Táto kartička už neplatí.", "This card is no longer valid.",
                           "Cette carte n'est plus valable.", "Esta tarjeta ya no es válida."),
    "card_invalid": ("✖ Kartičku sa nepodarilo overiť", "✖ The card could not be verified",
                     "✖ La carte n'a pas pu être vérifiée", "✖ No se ha podido verificar la tarjeta"),
    "language": ("Jazyk", "Language", "Langue", "Idioma"),
}


def pick_language(accept_language: str | None) -> str:
    """The first supported language from the Accept-Language header; Slovak otherwise."""
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGS:
            return code
    return "sk"


def variants(key: str) -> dict[str, str]:
    return dict(zip(LANGS, TEXTS[key], strict=True))
