"""Keyboard languages for BetterFrame Keyboard.

Covers the places the Steam Frame is sold (US, Canada, UK, Australia, Poland, the Eurozone/EU, and Japan,
Taiwan, Hong Kong and Korea through Komodo). Each language has its real letter layout. Extra accented letters
live on "accent layers": tap the accent key and the letter keys show their accented versions; tap it again for
the next set (for French: é → è → ê → ë).

Japanese, Chinese and Korean are typed through a converter (ime.py): what you type waits in the word bar,
turns into kanji / characters / Hangul there, and is sent when you pick it (or press Space / Enter).
"""

QWERTY = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
QWERTZ = ("qwertzuiop", "asdfghjkl", "yxcvbnm")


def L(code, name, rows=QWERTY, layers=(), currency="$", space=None, romaji=False, extra=(), kana=False, flick=False, numrow=None,
      after0=None, topleft=None, punct=None, ime=None, labels=None, fmtname=None,
      shift=None, mini=None, rtl=False, case=None):
    """numrow: the number row, as (key, with Shift) pairs, for languages whose real keyboard puts letters there
    (French é è ç à, Czech ě š č ř ž, ...). Digits are then on Shift, exactly like the real keyboard."""
    return {"code": code, "name": name, "rows": rows, "layers": [dict(x) for x in layers],
            "currency": currency, "space": space or name, "romaji": romaji, "extra": list(extra), "kana": kana, "flick": flick,
            "numrow": numrow, "after0": after0, "topleft": topleft, "punct": punct,
            "ime": ime, "labels": labels, "fmtname": fmtname,
            # shift: what Shift gives on letter keys of scripts without capitals (Thai, Hindi, Arabic, Hebrew)
            # mini: keys the Minimal layout's number row also needs (letters that live after 0 / top-left)
            # case: upper-case exceptions (Turkish i -> İ, ı -> I)
            "shift": (shift if isinstance(shift, dict) else dict(zip(*shift))) if shift else {}, "mini": mini, "rtl": rtl, "case": case or {}}


def m(pairs):
    """'a:á e:é' -> {'a': 'á', 'e': 'é'}"""
    return [tuple(p.split(":")) for p in pairs.split()]


def nr(keys, shifted="1234567890"):
    """Number-row pairs: letters on the keys, digits with Shift."""
    return list(zip(keys, shifted))


def digits(shifted):
    """A number row with the digits on the keys and this language's own symbols on Shift."""
    return list(zip("1234567890", shifted))


NORDIC = digits('!"#¤%&/()=')
EURO = digits('!"#$%&/()=')


# The accent key holds only what the real keyboard reaches with dead keys / AltGr; everything the real
# layout has on its own key is on its own key here too.
LANGS = [
    L("en-US", "English (US)", space="English"),
    L("en-GB", "English (UK)", currency="£", space="English (UK)"),
    # AZERTY: é è ç à on the number row (digits with Shift), ù next to m
    L("fr-FR", "Français", ("azertyuiop", "qsdfghjklmù", "wxcvbn"),
      [m("e:ê a:â u:û i:î o:ô"), m("e:ë i:ï u:ü y:ÿ"), m("o:œ a:æ")], "€",
      numrow=nr(["&", "é", '"', "'", "(", "-", "è", "_", "ç", "à"]), after0=[(")", "°"), ("=", "+")], topleft=("²", "³"),
      punct=[(",", "?"), (";", "."), (":", "/"), ("!", "§")]),
    # Canadian French (CSA): QWERTY; ç after p, è à after l, ù before z, é after the full stop
    L("fr-CA", "Français (Canada)", ("qwertyuiopç", "asdfghjklèà", "ùzxcvbnmé"),
      [m("e:ê a:â u:û i:î o:ô"), m("e:ë i:ï u:ü")], "$", space="Français (CA)",
      numrow=digits('!"/$%?&*()'), after0=[("-", "_"), ("=", "+")], topleft=("/", "\\"), punct=[(",", "'"), (".", '"')]),
    # German QWERTZ: ü ö ä beside the letters, ß right after 0 (also on the accent key, s:ß, for Minimal)
    L("de-DE", "Deutsch", ("qwertzuiopü", "asdfghjklöä", "yxcvbnm"), [m("s:ß")], "€",
      numrow=digits('!"§$%&/()='), after0=[("ß", "?"), ("´", "`")], topleft=("^", "°")),
    L("es-ES", "Español", ("qwertyuiop", "asdfghjklñç", "zxcvbnm"), [m("a:á e:é i:í o:ó u:ú"), m("u:ü")], "€",
      numrow=digits('!"·$%&/()='), after0=[("'", "?"), ("¡", "¿")], topleft=("º", "ª")),
    # Italian: è on the top row, ò à ù on the middle row
    L("it-IT", "Italiano", ("qwertyuiopè", "asdfghjklòàù", "zxcvbnm"), [m("e:é i:ì o:ó")], "€",
      numrow=digits('!"£$%&/()='), after0=[("'", "?"), ("ì", "^")], topleft=("\\", "|")),
    L("pt-PT", "Português", ("qwertyuiop", "asdfghjklç", "zxcvbnm"),
      [m("a:á e:é i:í o:ó u:ú"), m("a:ã o:õ"), m("a:â e:ê o:ô"), m("a:à")], "€",
      numrow=EURO, after0=[("'", "?"), ("«", "»")], topleft=("\\", "|")),
    L("nl-NL", "Nederlands", QWERTY, [m("e:é a:á o:ó i:í u:ú"), m("e:ë i:ï o:ö u:ü"), m("e:è a:à")], "€"),
    # Polish programmer's layout: QWERTY, Polish letters with AltGr (here: the accent key)
    L("pl-PL", "Polski", QWERTY, [m("a:ą c:ć e:ę l:ł n:ń o:ó s:ś z:ż x:ź")], "zł"),
    L("sv-SE", "Svenska", ("qwertyuiopå", "asdfghjklöä", "zxcvbnm"), [m("e:é")], "kr",
      numrow=NORDIC, after0=[("+", "?"), ("´", "`")], topleft=("§", "½")),
    L("fi-FI", "Suomi", ("qwertyuiopå", "asdfghjklöä", "zxcvbnm"), [m("s:š z:ž")], "€",
      numrow=NORDIC, after0=[("+", "?"), ("´", "`")], topleft=("§", "½")),
    L("da-DK", "Dansk", ("qwertyuiopå", "asdfghjklæø", "zxcvbnm"), [m("e:é")], "kr",
      numrow=NORDIC, after0=[("+", "?"), ("´", "`")], topleft=("½", "§")),
    L("nb-NO", "Norsk", ("qwertyuiopå", "asdfghjkløæ", "zxcvbnm"), [m("e:é")], "kr",
      numrow=NORDIC, after0=[("+", "?"), ("\\", "`")], topleft=("|", "§")),
    L("el-GR", "Ελληνικά", (";ςερτυθιοπ", "ασδφγηξκλ", "ζχψωβνμ"),
      [m("α:ά ε:έ η:ή ι:ί ο:ό υ:ύ ω:ώ"), m("ι:ϊ υ:ϋ"), m("ι:ΐ υ:ΰ")], "€", after0=[("-", "_"), ("=", "+")]),
    # Czech QWERTZ: ě š č ř ž ý á í é on the number row, ú and ů beside the letters
    L("cs-CZ", "Čeština", ("qwertzuiopú", "asdfghjklů", "yxcvbnm"), [m("d:ď t:ť n:ň o:ó")], "Kč",
      numrow=nr(["+", "ě", "š", "č", "ř", "ž", "ý", "á", "í", "é"]), after0=[("=", "%"), ("´", "ˇ")], topleft=(";", "°"),
      punct=[(",", "?"), (".", ":"), ("-", "_")]),
    # Slovak QWERTZ: ľ š č ť ž ý á í é on the number row, ú ä ô ň beside the letters
    L("sk-SK", "Slovenčina", ("qwertzuiopúä", "asdfghjklôň", "yxcvbnm"), [m("d:ď o:ó r:ŕ l:ĺ")], "€",
      numrow=nr(["+", "ľ", "š", "č", "ť", "ž", "ý", "á", "í", "é"]), after0=[("=", "%"), ("´", "ˇ")], topleft=(";", "°"),
      punct=[(",", "?"), (".", ":"), ("-", "_")]),
    # Slovenian / Croatian QWERTZ: š đ on the top row, č ć ž on the middle row
    L("sl-SI", "Slovenščina", ("qwertzuiopšđ", "asdfghjklčćž", "yxcvbnm"), (), "€",
      numrow=EURO, after0=[("'", "?"), ("+", "*")], topleft=("¸", "¨")),
    L("hr-HR", "Hrvatski", ("qwertzuiopšđ", "asdfghjklčćž", "yxcvbnm"), (), "€",
      numrow=EURO, after0=[("'", "?"), ("+", "*")], topleft=("¸", "¨")),
    # Hungarian QWERTZ: ő ú, é á ű and í on their own keys; ö ü ó with the accent key
    # Hungarian QWERTZ: ö ü right after 0 (ó on the accent key); ő ú, é á ű and í on their own keys
    L("hu-HU", "Magyar", ("qwertzuiopőú", "asdfghjkléáű", "íyxcvbnm"), [m("o:ö u:ü"), m("o:ó")], "Ft",
      numrow=digits("'\"+!%/=()§"), after0=[("ö", "Ö"), ("ü", "Ü")], punct=[(",", "?"), (".", ":"), ("-", "_")]),
    # Romanian standard: ă î on the top row, ș ț on the middle row, â with the accent key
    L("ro-RO", "Română", ("qwertyuiopăî", "asdfghjklșțâ", "zxcvbnm"), (), "lei", topleft=("„", "”")),
    # Estonian: ü õ on the top row, ö ä on the middle row
    L("et-EE", "Eesti", ("qwertyuiopüõ", "asdfghjklöä", "zxcvbnm"), [m("s:š z:ž")], "€",
      numrow=NORDIC, after0=[("+", "?"), ("´", "`")], topleft=("ˇ", "~")),
    # Latvian (QWERTY): long vowels and soft consonants with AltGr (here: the accent key)
    L("lv-LV", "Latviešu", QWERTY, [m("a:ā c:č e:ē g:ģ i:ī k:ķ l:ļ n:ņ s:š u:ū z:ž")], "€"),
    # Lithuanian: ą č ę ė į š ų ū on the number row, ž with the accent key
    L("lt-LT", "Lietuvių", QWERTY, [m("z:ž")], "€",
      numrow=nr(["ą", "č", "ę", "ė", "į", "š", "ų", "ū", "9", "0"], "12345678()"), after0=[("-", "_"), ("ž", "Ž")], punct=[(",", "<"), (".", ">"), ("/", "?")]),
    # Bulgarian: the standard (BDS) layout; the phonetic one many people prefer (я в е р т ъ...) is the next entry
    L("bg-BG", "Български", [[(",", "ы")] + list("уеишщксдзц") + [(";", "§")], "ьяаожгтнвмч", "юйъэфхпрлб"], [m("и:ѝ")], "€",
      space="Български", fmtname="БДС", numrow=digits('!?+"%=:/–№'), after0=[("-", "$"), (".", "€")], topleft=("(", ")"), punct=[]),
    L("bg-PH", "Български (фон.)", ["явертъуиопшщ", list("асдфгхйкл") + [(";", ":"), ("'", '"'), "ю"],
                                     list("зьцжбнм") + [(",", "„"), (".", "“"), ("/", "?")]], [m("и:ѝ")], "€",
      space="Български", fmtname="Фонетична", numrow=digits('!@№$%€§*()'), after0=[("-", "–"), ("=", "+")], topleft=("ч", "Ч"), punct=[]),
    L("es-419", "Español (Latam)", ("qwertyuiop", list("asdfghjklñ") + [("{", "[")], "zxcvbnm"),
      [m("a:á e:é i:í o:ó u:ú"), m("u:ü")], "$", space="Español", numrow=digits('!"#$%&/()='),
      after0=[("'", "?"), ("¿", "¡")], topleft=("|", "°"), punct=[(",", ";"), (".", ":"), ("-", "_")]),
    # Catalan, Basque and Galician are typed on the Spanish keyboard (ñ ç on their own keys, · with Shift+3)
    L("ca-ES", "Català", ("qwertyuiop", "asdfghjklñç", "zxcvbnm"), [m("a:à e:è o:ò"), m("e:é i:í o:ó u:ú"), m("i:ï u:ü")], "€",
      numrow=digits('!"·$%&/()='), after0=[("'", "?"), ("¡", "¿")], topleft=("º", "ª")),
    L("eu-ES", "Euskara", ("qwertyuiop", "asdfghjklñç", "zxcvbnm"), [m("a:á e:é i:í o:ó u:ú"), m("u:ü")], "€",
      numrow=digits('!"·$%&/()='), after0=[("'", "?"), ("¡", "¿")], topleft=("º", "ª")),
    L("gl-ES", "Galego", ("qwertyuiop", "asdfghjklñç", "zxcvbnm"), [m("a:á e:é i:í o:ó u:ú"), m("u:ü")], "€",
      numrow=digits('!"·$%&/()='), after0=[("'", "?"), ("¡", "¿")], topleft=("º", "ª")),
    # Irish: the UK/Irish keyboard, fadas with AltGr (here: the accent key)
    L("ga-IE", "Gaeilge", QWERTY, [m("a:á e:é i:í o:ó u:ú")], "€", numrow=digits('!"£$%^&*()'),
      after0=[("-", "_"), ("=", "+")], topleft=("`", "¬"), punct=[(",", "<"), (".", ">"), ("/", "?")]),
    # Maltese (MSA 100:2002, 47 keys): ġ ħ after p, ż where # is, ċ top-left
    L("mt-MT", "Malti", ("qwertyuiopġħ", "asdfghjkl", "zxcvbnm"), [m("c:ċ z:ż g:ġ h:ħ"), m("a:à e:è i:ì o:ò u:ù")], "€",
      numrow=digits('!"€$%^&*()'), after0=[("-", "_"), ("=", "+")], topleft=("ċ", "Ċ"), punct=[(",", "<"), (".", ">"), ("/", "?")]),
    # Russian ЙЦУКЕН: ё top-left on a real keyboard, on the accent key here too (Minimal has no top-left key)
    L("ru-RU", "Русский", ("йцукенгшщзхъ", "фывапролджэ", list("ячсмитьбю") + [(".", ",")]), [m("е:ё")], "₽",
      numrow=digits('!"№;%:?*()'), after0=[("-", "_"), ("=", "+")], topleft=("ё", "Ё"), punct=[]),
    # Ukrainian: і ї є ґ have their own keys; the apostrophe (м'ясо) top-left
    L("uk-UA", "Українська", ("йцукенгшщзхї", "фівапролджєґ", list("ячсмитьбю") + [(".", ",")]), (), "₴",
      numrow=digits('!"№;%:?*()'), after0=[("-", "_"), ("=", "+")], topleft=("'", "₴"), punct=[]),
    # Brazilian Portuguese ABNT2: ç beside l, the accents are dead keys (here: the accent key)
    L("pt-BR", "Português (Brasil)", ("qwertyuiop", list("asdfghjklç") + [("~", "^")], "zxcvbnm"),
      [m("a:á e:é i:í o:ó u:ú"), m("a:ã o:õ"), m("a:â e:ê o:ô"), m("a:à u:ü")], "R$", space="Português",
      numrow=digits('!@#$%¨&*()'), after0=[("-", "_"), ("=", "+")], topleft=("'", '"')),
    # Turkish Q: ı and i are two different letters (I / İ in capitals)
    L("tr-TR", "Türkçe", ("qwertyuıopğü", "asdfghjklşi", "zxcvbnmöç"), (), "₺",
      numrow=digits("!'^+%&/()="), after0=[("*", "?"), ("-", "_")], topleft=('"', "é"), punct=[(".", ":"), (",", ";")],
      case={"i": "İ", "ı": "I"}, fmtname="Q"),
    # Vietnamese: typed with Telex (aa â, ow ơ, dd đ; s f r x j add the tones), the way phones do it
    L("vi-VN", "Tiếng Việt", QWERTY, (), "₫", ime="vi", fmtname="Telex"),
    L("id-ID", "Bahasa Indonesia", QWERTY, (), "Rp", space="Indonesia"),
    L("ms-MY", "Bahasa Melayu", QWERTY, (), "RM", space="Melayu"),
    # Arabic (the standard 101 layout). Arabic is written right to left: the apps you type into show it that way
    L("ar", "العربية", ("ضصثقفغعهخحجد", "شسيبلاتنمكط", "ئءؤرﻻىةوزظ"), (), "$", space="العربية", fmtname="العربية",
      numrow=digits('!@#$%^&*)('), after0=[("-", "_"), ("=", "+")], topleft=("ذ", "\u0651"), punct=[], rtl=True,
      shift=("ضصثقفغعهخحجدشسيبلاتنمكطئءؤرﻻىةوزظ", "\u064e\u064b\u064f\u064cﻹإ`÷×\u061b<>\u0650\u064d][ﻷأـ\u060c/:\"~\u0652}{ﻵآ',.\u061f"), mini=[("ذ", "\u0651")]),
    # Hebrew (SI-1452): Shift gives capital English letters, as on a real Hebrew keyboard
    L("he-IL", "עברית", [[("/", "Q"), ("'", "W")] + list("קראטוןםפ") + [("]", "}"), ("[", "{")], list("שדגכעיחלךף") + [(",", '"')], list("זסבהנמצתץ") + [(".", "?")]],
      (), "₪", space="עברית", fmtname="עברית", numrow=digits('!@#$%^&*)('), after0=[("-", "_"), ("=", "+")], topleft=(";", "~"),
      punct=[], rtl=True, shift=("קראטוןםפשדגכעיחלךףזסבהנמצתץ", "ERTYUIOPASDFGHJKL:ZXCVBNM><")),
    # Hindi: InScript, the Indian standard (vowel signs on the left, consonants on the right; Shift for the rest)
    L("hi-IN", "हिन्दी", ("ौैाीूबहगदजड़ॉ", "ोे्िुपरकतचट", list("ॆंमनवलस") + [(",", "ष"), (".", "।")] + ["य"]), (), "₹",
      space="हिन्दी", fmtname="इनस्क्रिप्ट", numrow=nr(list("१२३४५६७८९०"), "ऍॅ#$%^&*()"), after0=[("-", "ः"), ("ृ", "ऋ")],
      topleft=("ॊ", "ऒ"), punct=[], mini=[("ृ", "ऋ")],
      shift=dict(zip("ौैाीूबहगदजड़ॉोे्िुपरकतचटॆंमनवलसय", list("औऐआईऊभङघधझढञऑओएअइउफऱखथछठऎँणऩऴळश") + ["य\u093c"]))),
    # Thai: Kedmanee, the standard; letters on the number row too (Thai digits with Shift)
    L("th-TH", "ไทย", ("ๆไำพะัีรนยบล", "ฟหกดเ้่าสวง", "ผปแอิืทมใฝ"), (), "฿", space="ไทย", fmtname="เกษมณี",
      numrow=nr(list("ๅ/-ภถุึคตจ"), "+๑๒๓๔ู฿๕๖๗"), after0=[("ข", "๘"), ("ช", "๙")], topleft=("_", "%"), punct=[],
      mini=[("ข", "๘"), ("ช", "๙")],
      shift=("ๆไำพะัีรนยบลฟหกดเ้่าสวงผปแอิืทมใฝ", "๐\"ฎฑธํ๊ณฯญฐ,ฤฆฏโฌ็๋ษศซ.()ฉฮฺ์?ฒฬฦ")),
    L("ja-JP", "日本語 かな", QWERTY, (), "¥", kana=True, ime="ja"),
    L("ja-JP-r", "日本語 ローマ字", QWERTY, (), "¥", romaji=True, ime="ja"),
    L("ja-JP-f", "日本語 フリック", QWERTY, (), "¥", kana=True, flick=True, ime="ja"),
    # Korean: 2-set (Dubeolsik), the standard; Shift gives the doubled consonants and ㅒ ㅖ
    L("ko-KR", "한국어", ("ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔ", "ㅁㄴㅇㄹㅎㅗㅓㅏㅣ", "ㅋㅌㅊㅍㅠㅜㅡ"), (), "₩", ime="ko", fmtname="두벌식"),
    # Taiwan: Zhuyin on the standard (Dachen) layout; tones ˊ ˇ ˋ ˙ on the number row, Space is the 1st tone
    L("zh-TW", "中文 注音", ("ㄆㄊㄍㄐㄔㄗㄧㄛㄟㄣ", "ㄇㄋㄎㄑㄕㄘㄨㄜㄠㄤ", "ㄈㄌㄏㄒㄖㄙㄩㄝㄡㄥ"), (), "$", space="注音", fmtname="大千",
      numrow=nr(["ㄅ", "ㄉ", "ˇ", "ˋ", "ㄓ", "ˊ", "˙", "ㄚ", "ㄞ", "ㄢ"]), after0=[("ㄦ", "_"), ("=", "+")], ime="zhuyin"),
    # Hong Kong: Cangjie (5th generation) and Quick, the letters show their Cangjie radicals
    L("zh-HK", "中文 倉頡", QWERTY, (), "$", space="倉頡", ime="cangjie", labels="cangjie", fmtname="倉頡"),
    L("zh-HK-q", "中文 速成", QWERTY, (), "$", space="速成", ime="quick", labels="cangjie", fmtname="速成"),
    L("zh-CN", "中文 拼音", QWERTY, (), "¥", space="拼音", ime="pinyin-s"),
]

_ORDER = ["en-US", "en-GB", "ga-IE", "es-ES", "es-419", "ca-ES", "eu-ES", "gl-ES", "fr-FR", "fr-CA", "de-DE", "it-IT", "pt-PT", "pt-BR",
          "nl-NL", "pl-PL", "sv-SE", "fi-FI", "da-DK", "nb-NO", "el-GR", "bg-BG", "bg-PH", "cs-CZ", "sk-SK", "sl-SI",
          "hr-HR", "hu-HU", "ro-RO", "et-EE", "lv-LV", "lt-LT", "mt-MT", "ru-RU", "uk-UA", "tr-TR",
          "id-ID", "ms-MY", "vi-VN", "ar", "he-IL", "hi-IN", "th-TH",
          "ja-JP-r", "ja-JP", "ja-JP-f", "ko-KR", "zh-TW", "zh-HK", "zh-HK-q", "zh-CN"]
LANGS.sort(key=lambda l: _ORDER.index(l["code"]) if l["code"] in _ORDER else 999)
BY_CODE = {l["code"]: l for l in LANGS}

# The language picker: each button shows the language's own name, and underneath, which variant it is
PICK = {"en-US": ("English", "US"), "en-GB": ("English", "UK"), "es-ES": ("Español", "España"),
        "es-419": ("Español", "Latinoamérica"), "fr-FR": ("Français", "France"), "fr-CA": ("Français", "Canada"),
        "bg-BG": ("Български", "БДС"), "bg-PH": ("Български", "фонетична"),
        "pt-PT": ("Português", "Portugal"), "pt-BR": ("Português", "Brasil"), "id-ID": ("Bahasa", "Indonesia"),
        "ms-MY": ("Bahasa", "Melayu"), "vi-VN": ("Tiếng Việt", "Telex"), "hi-IN": ("हिन्दी", "InScript"),
        "ja-JP-r": ("日本語", "ローマ字"), "ja-JP": ("日本語", "かな"), "ja-JP-f": ("日本語", "フリック"),
        "zh-TW": ("中文", "注音 · 繁體"), "zh-HK": ("中文", "倉頡"), "zh-HK-q": ("中文", "速成"), "zh-CN": ("中文", "拼音 · 简体")}


def pick_label(lang):
    return PICK.get(lang["code"], (lang["name"], ""))


# The language picker shows each language once (English, Español, 日本語...); one with more than one keyboard
# (English US / UK, Japanese romaji / kana / flick) asks which next
_GROUP_NAME = {"id": "Bahasa Indonesia", "ms": "Bahasa Melayu"}


def groups():
    """[(key, name, [langs])] in the picker's order."""
    out, seen = [], {}
    for l in LANGS:
        key = l["code"].split("-")[0]
        if key not in seen:
            seen[key] = len(out)
            out.append((key, _GROUP_NAME.get(key) or pick_label(l)[0], []))
        out[seen[key]][2].append(l)
    return out


def variant_label(lang):
    return pick_label(lang)[1] or native_format(lang)


# Korean: what Shift gives on each jamo key
KO_SHIFT = dict(zip("ㅂㅈㄷㄱㅅㅐㅔ", "ㅃㅉㄸㄲㅆㅒㅖ"))
# Cangjie: the radical on each letter key
CANGJIE = dict(zip("abcdefghijklmnopqrstuvwxy", "日月金木水火土竹戈十大中一弓人心手口尸廿山女田難卜"))
# full-width punctuation for Chinese
ZH_PUNCT = {",": "，", ".": "。", "?": "？", "!": "！", ":": "：", ";": "；", "(": "（", ")": "）", "[": "「", "]": "」",
            "<": "《", ">": "》", "\\": "、"}


# --------------------------------------------------------------------------- key layouts (letter arrangements)
# Each row is a list of keys: a letter, or a (key, with Shift) pair for punctuation that sits among the letters.
def _r(s):
    return list(s)


FORMATS = {
    "qwerty": ("QWERTY", [_r("qwertyuiop"), _r("asdfghjkl"), _r("zxcvbnm")]),
    "qwertz": ("QWERTZ", [_r("qwertzuiop"), _r("asdfghjkl"), _r("yxcvbnm")]),
    "azerty": ("AZERTY", [_r("azertyuiop"), _r("qsdfghjklm"), _r("wxcvbn")]),
    "dvorak": ("Dvorak", [[("'", '"'), (",", "<"), (".", ">")] + _r("pyfgcrl"), _r("aoeuidhtns"), [(";", ":")] + _r("qjkxbmwvz")]),
    "colemak": ("Colemak", [_r("qwfpgjluy") + [(";", ":")], _r("arstdhneio"), _r("zxcvbkm")]),
    "colemak-dh": ("Colemak-DH", [_r("qwfpbjluy") + [(";", ":")], _r("arstgmneio"), _r("zxcdvkh")]),
}
FORMAT_ORDER = ["default", "qwerty", "qwertz", "azerty", "dvorak", "colemak", "colemak-dh"]
_LATIN = set("abcdefghijklmnopqrstuvwxyz")


def native_format(lang):
    """Name of the arrangement a language uses by default (QWERTY, QWERTZ, AZERTY...)."""
    if lang.get("fmtname"):
        return lang["fmtname"]
    if lang.get("kana"):
        return "かな"
    if not set(lang["rows"][0]) & _LATIN:
        return lang["name"]
    first = lang["rows"][0][:6]
    return {"qwerty": "QWERTY", "qwertz": "QWERTZ", "azerty": "AZERTY"}.get(first, "QWERTY")


def can_reformat(lang):
    """The six layouts arrange Latin letters; Greek, Cyrillic, Japanese kana, Hangul and Zhuyin keep their own keyboards."""
    return not lang.get("kana") and lang.get("ime") not in ("zhuyin", "ko", "cangjie", "quick") and bool(set(lang["rows"][0]) & _LATIN)


def letter_rows(lang, fmt="default"):
    """The three letter rows for this language in the chosen layout. The language's own letters (ü, ñ, å...)
    stay on the keyboard: they're added at the end of the same row as in the language's layout."""
    rows = [list(r) for r in lang["rows"]]
    if fmt in FORMATS and can_reformat(lang):
        base = FORMATS[fmt][1]
        out = []
        for i in range(3):
            own = [c for c in rows[i] if c not in _LATIN and c != ";"]
            out.append(list(base[i]) + own)
        return out
    return rows


def format_label(lang, fmt):
    if fmt in FORMATS and can_reformat(lang):
        return FORMATS[fmt][0]
    return native_format(lang)


def get(code):
    return BY_CODE.get(code) or LANGS[0]


_CUR = {"shift": {}, "case": {}}


def set_lang(code):
    """The language being typed (for Shift on scripts without capitals, and Turkish i / İ)."""
    lang = BY_CODE.get(code) or LANGS[0]
    _CUR["shift"], _CUR["case"] = lang.get("shift") or {}, lang.get("case") or {}


def shifted(c):
    """What a letter key types with Shift held: the capital, or (Thai, Hindi, Arabic, Hebrew) the key's second letter."""
    return _CUR["shift"].get(c) or upper(c)


TYPES = {"ﻻ": "لا", "ﻷ": "لأ", "ﻹ": "لإ", "ﻵ": "لآ"}  # Arabic lam-alef keys type the two letters


def show(c):
    """A key label: a vowel sign or tone mark on its own is drawn on a dotted circle, the way keyboards show it."""
    import unicodedata
    return "\u25cc" + c if len(c) == 1 and unicodedata.category(c) in ("Mn", "Mc") else c


def upper(c):
    """Upper case (Shift), but never turn one letter into two (ß stays ß). Hiragana become katakana."""
    if c in _CUR["case"]:
        return _CUR["case"][c]
    if "\u3041" <= c <= "\u3096":
        return chr(ord(c) + 0x60)
    if c in KO_SHIFT:
        return KO_SHIFT[c]
    u = c.upper()
    return u if len(u) == 1 else c


# --------------------------------------------------------------------------- Japanese kana keyboard (50-sound layout)
# Columns are the consonant rows (あ か さ た な は ま や ら わ), rows are the vowels, like console kana keyboards.
KANA_ROWS = [
    "あかさたなはまやらわ",
    "いきしちにひみ、りを",
    "うくすつぬふむゆるん",
    "えけせてねへめ。れー",
    "おこそとのほもよろ？",
]
_DAKU = dict(zip("かきくけこさしすせそたちつてとはひふへほう", "がぎぐげござじずぜぞだぢづでどばびぶべぼゔ"))
_HANDAKU = dict(zip("はひふへほ", "ぱぴぷぺぽ"))
_SMALL = dict(zip("あいうえおつやゆよわ", "ぁぃぅぇぉっゃゅょゎ"))


def _cycle(c, steps):
    """Next form of a kana for a key that cycles through forms (e.g. は → ば → ぱ → は)."""
    kata = "\u30a1" <= c <= "\u30f6"
    h = chr(ord(c) - 0x60) if kata else c
    for seq in steps:
        if h in seq:
            n = seq[(seq.index(h) + 1) % len(seq)]
            return chr(ord(n) + 0x60) if kata else n
    return None


_DAKU_SEQS = [[b, _DAKU[b]] + ([_HANDAKU[b]] if b in _HANDAKU else []) for b in _DAKU]
_SMALL_SEQS = [[b, _SMALL[b]] for b in _SMALL]


# --------------------------------------------------------------------------- Japanese flick keypad (like a phone)
# Each key: (middle, left, up, right, down). Tap for the middle one, or press and flick toward another.
FLICK = [
    ["あいうえお", "かきくけこ", "さしすせそ"],
    ["たちつてと", "なにぬねの", "はひふへほ"],
    ["まみむめも", "や「ゆ」よ", "らりるれろ"],
    [None, "わをんー", "、。？！…"],
]
_MOD_SEQS = [[b, _SMALL[b]] + ([_DAKU[b]] if b in _DAKU else []) for b in _SMALL] + \
            [[b, _DAKU[b]] + ([_HANDAKU[b]] if b in _HANDAKU else []) for b in _DAKU if b not in _SMALL]


def flick_mod(c):
    """The ゛゜小 key, like a phone: つ → っ → づ, は → ば → ぱ, や → ゃ ... (and back)."""
    return _cycle(c, _MOD_SEQS)


def dakuten(c):
    """゛゜ key: か → が, は → ば → ぱ → は ..."""
    return _cycle(c, _DAKU_SEQS)


def small(c):
    """小 key: つ → っ, や → ゃ ..."""
    return _cycle(c, _SMALL_SEQS)


# --------------------------------------------------------------------------- Japanese: romaji -> kana
_KANA = {
    "a": "あ", "i": "い", "u": "う", "e": "え", "o": "お",
    "ka": "か", "ki": "き", "ku": "く", "ke": "け", "ko": "こ",
    "sa": "さ", "shi": "し", "si": "し", "su": "す", "se": "せ", "so": "そ",
    "ta": "た", "chi": "ち", "ti": "ち", "tsu": "つ", "tu": "つ", "te": "て", "to": "と",
    "na": "な", "ni": "に", "nu": "ぬ", "ne": "ね", "no": "の",
    "ha": "は", "hi": "ひ", "fu": "ふ", "hu": "ふ", "he": "へ", "ho": "ほ",
    "ma": "ま", "mi": "み", "mu": "む", "me": "め", "mo": "も",
    "ya": "や", "yu": "ゆ", "yo": "よ",
    "ra": "ら", "ri": "り", "ru": "る", "re": "れ", "ro": "ろ",
    "wa": "わ", "wo": "を", "n'": "ん",
    "ga": "が", "gi": "ぎ", "gu": "ぐ", "ge": "げ", "go": "ご",
    "za": "ざ", "ji": "じ", "zi": "じ", "zu": "ず", "ze": "ぜ", "zo": "ぞ",
    "da": "だ", "di": "ぢ", "du": "づ", "de": "で", "do": "ど",
    "ba": "ば", "bi": "び", "bu": "ぶ", "be": "べ", "bo": "ぼ",
    "pa": "ぱ", "pi": "ぴ", "pu": "ぷ", "pe": "ぺ", "po": "ぽ",
    "kya": "きゃ", "kyu": "きゅ", "kyo": "きょ", "sha": "しゃ", "shu": "しゅ", "sho": "しょ",
    "sya": "しゃ", "syu": "しゅ", "syo": "しょ", "cha": "ちゃ", "chu": "ちゅ", "cho": "ちょ",
    "tya": "ちゃ", "tyu": "ちゅ", "tyo": "ちょ", "nya": "にゃ", "nyu": "にゅ", "nyo": "にょ",
    "hya": "ひゃ", "hyu": "ひゅ", "hyo": "ひょ", "mya": "みゃ", "myu": "みゅ", "myo": "みょ",
    "rya": "りゃ", "ryu": "りゅ", "ryo": "りょ", "gya": "ぎゃ", "gyu": "ぎゅ", "gyo": "ぎょ",
    "ja": "じゃ", "ju": "じゅ", "jo": "じょ", "jya": "じゃ", "jyu": "じゅ", "jyo": "じょ",
    "bya": "びゃ", "byu": "びゅ", "byo": "びょ", "pya": "ぴゃ", "pyu": "ぴゅ", "pyo": "ぴょ",
    "fa": "ふぁ", "fi": "ふぃ", "fe": "ふぇ", "fo": "ふぉ", "vu": "ゔ", "va": "ゔぁ", "vi": "ゔぃ",
    "ve": "ゔぇ", "vo": "ゔぉ", "she": "しぇ", "je": "じぇ", "che": "ちぇ", "thi": "てぃ", "dhi": "でぃ",
    "xa": "ぁ", "xi": "ぃ", "xu": "ぅ", "xe": "ぇ", "xo": "ぉ", "la": "ぁ", "li": "ぃ", "lu": "ぅ",
    "le": "ぇ", "lo": "ぉ", "xya": "ゃ", "xyu": "ゅ", "xyo": "ょ", "xtsu": "っ", "xtu": "っ", "-": "ー",
}
_PREFIXES = {k[:i] for k in _KANA for i in range(1, len(k) + 1)} | {"tc"}  # "tch" (matcha) -> っち
JA_PUNCT = {",": "、", ".": "。", "?": "？", "!": "！", "[": "「", "]": "」", "-": "ー"}


class Romaji:
    """Turns romaji typed so far into kana. feed(letter) returns (backspaces, kana) when letters
    already typed should be replaced, else None."""

    def __init__(self):
        self.buf = ""

    def reset(self):
        self.buf = ""

    def back(self):
        self.buf = self.buf[:-1]

    def feed(self, c):
        """Returns (letters to erase, text to type instead) when kana are ready, else None. The whole group of
        romaji letters waiting on screen is replaced at once, with any still-pending letters typed back after."""
        self.buf += c.lower()
        on_screen = len(self.buf)
        out, erase = "", 0
        while self.buf:
            b = self.buf
            if b in _KANA and not any(k != b and k.startswith(b) for k in _KANA):
                out, erase, self.buf = out + _KANA[b], erase + len(b), ""
            elif (len(b) >= 2 and b[0] == b[1] and b[0] not in "aiueon" and b[0].isalpha()) or b.startswith("tch"):
                out, erase, self.buf = out + "っ", erase + 1, b[1:]  # double consonant: small tsu
            elif b.startswith("nn"):  # nn: ん (nni -> んに, like konnichiha; nng -> んg; a lone nn waits)
                if len(b) == 2:
                    break
                if b[2] == "'":
                    out, erase, self.buf = out + "ん", erase + 3, b[3:]
                    continue
                out, erase, self.buf = out + "ん", erase + (1 if b[2] in "aiueoy" else 2), b[1:] if b[2] in "aiueoy" else b[2:]
            elif b[0] == "n" and len(b) >= 2 and b[1] not in "aiueoy'":  # n + consonant -> ん
                out, erase, self.buf = out + "ん", erase + 1, b[1:]
            elif b in _PREFIXES:
                if b in _KANA and len(b) == 1:  # a lone vowel never starts anything longer
                    out, erase, self.buf = out + _KANA[b], erase + 1, ""
                break  # wait for more letters
            else:  # no kana starts like this: the first letter stays as typed
                out, erase, self.buf = out + b[0], erase + 1, b[1:]
        return (on_screen, out + self.buf) if out else None

    def flush(self):
        """A lone 'n' (or 'nn') at the end becomes ん (e.g. before a space)."""
        if self.buf in ("n", "nn"):
            n = len(self.buf)
            self.buf = ""
            return (n, "ん")
        if self.buf == "n":
            self.buf = ""
            return (1, "ん")
        self.buf = ""
        return None
