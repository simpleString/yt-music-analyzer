"""Dictionary-based topic modeling of song lyrics (RU/EN).

A topic is a set of stems; a normalized vector {topic: match share}
is extracted. The approach mirrors sentiment_score from lyrics.py:
counting lowercase stem occurrences.
"""

import json
import re

TOPIC_DICTS: dict[str, dict[str, tuple[str, ...]]] = {
    "love": {
        "ru": (
            "любл люблю любовь любим мила милая милый нежн нежность поцелуй "
            "сердц сердечн обним встреч влюб скучаю ревн"
        ),
        "en": (
            "love heart kiss hold embrace miss darling baby sweet tender "
            "forever together soul"
        ),
    },
    "separation and loss": {
        "ru": (
            "прощай ушёл ушла ушли верн забыл забыла разрыв расста потеря "
            "одинок пуст тоск груст печал слез слёз плач рыда брошен"
        ),
        "en": (
            "goodbye leaving gone left alone lonely lost missing broken "
            "break cry crying tears farewell empt"
        ),
    },
    "city and streets": {
        "ru": (
            "город улиц квартал двор проспект метро троллейбус автобус "
            "фонар асфальт подъезд крыш окраин центр район витрин неон"
        ),
        "en": (
            "city street downtown block avenue traffic subway neon "
            "pavement rooftop neighborhood boulevard"
        ),
    },
    "road and travel": {
        "ru": (
            "дорог путь ед еду поезд самолёт вокзал чемодан маршрут "
            "километр шоссе путешеств бегу иду идём уезжаю"
        ),
        "en": (
            "road highway journey train plane travel miles walk running "
            "driving ride destination trip path"
        ),
    },
    "night and sleep": {
        "ru": (
            "ночь ночной бессонниц сон сновиден луна звёзд звезда полноч "
            "темнот сумрак засыпаю просну утро рассвет заря"
        ),
        "en": (
            "night midnight moon star sleep dream asleep insomnia dark "
            "dawn sunrise twilight shadow evening"
        ),
    },
    "nature": {
        "ru": (
            "море океан волн берег рек лес гор поле небо дожд гроза "
            "ветер снег зим лето весн осен солнц трав цветок листв"
        ),
        "en": (
            "sea ocean wave shore river forest mountain field sky rain "
            "storm wind snow winter summer autumn sun grass flower leaf"
        ),
    },
    "war and struggle": {
        "ru": (
            "война враг бой битва сражен оруж пул огон солдат арм "
            "защит герой знамен побед сражат борьб сил"
        ),
        "en": (
            "war enemy battle fight soldier gun fire army weapon hero "
            "victory flag struggle survive defend"
        ),
    },
    "freedom and rebellion": {
        "ru": (
            "свобод вол бунт протест правил запрет клетк цеп побег "
            "сбежал революц знам независим своем волен"
        ),
        "en": (
            "free freedom rebel protest rules chains escape run away "
            "revolution independent wild"
        ),
    },
    "party and dance": {
        "ru": (
            "танц танцую вечеринк друз гуля праздник клуб музык "
            "весел хлопа двига диджей"
        ),
        "en": (
            "dance dancing party club tonight friends fun music play "
            "jump drink celebrate dj beat"
        ),
    },
    "inner search": {
        "ru": (
            "кто я зачем смысл жизнь судь ищ ищу ответ вопрос "
            "душ вера надежд мечт цель позна себя истин"
        ),
        "en": (
            "meaning life fate destiny answer question soul faith hope "
            "dream truth find myself reason"
        ),
    },
}

RU_TOPICS = {name: d["ru"] for name, d in TOPIC_DICTS.items()}
EN_TOPICS = {name: d["en"] for name, d in TOPIC_DICTS.items()}


_WORD_RE = re.compile(r"[a-zа-яё]+")


def _count_stems(text: str, stems: tuple[str, ...]) -> int:
    """Number of words starting with one of the stems."""
    stem_set = frozenset(stems.split() if isinstance(stems, str) else stems)
    n = 0
    for word in _WORD_RE.findall(text):
        # prefix matching: it suffices that the word starts with a known stem
        for length in range(min(len(word), 8), 1, -1):
            if word[:length] in stem_set:
                n += 1
                break
    return n


def extract_topics(text: str, language: str = "") -> dict[str, float]:
    """Normalized topic vector for a text.

    Returns {topic: weight in 0..1} with weights summing to 1 (if there
    are matches), otherwise {}. language: "ru"/"en"/"" — with "" it is
    detected automatically.
    """
    from app.services.lyrics import detect_language

    t = (text or "").lower()
    if not t:
        return {}
    lang = language or detect_language(t)
    dicts = RU_TOPICS if lang == "ru" else EN_TOPICS
    raw = {name: _count_stems(t, stems) for name, stems in dicts.items()}
    total = sum(raw.values())
    if total == 0:
        return {}
    return {name: round(v / total, 4) for name, v in raw.items() if v > 0}


def dominant_topic(vector_json: str) -> str:
    """Name of the dominant topic from a json vector ('' if empty)."""
    try:
        vec = json.loads(vector_json) if vector_json else {}
    except ValueError:
        return ""
    if not vec:
        return ""
    return max(vec, key=lambda k: vec[k])
