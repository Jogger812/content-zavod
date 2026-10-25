#!/usr/bin/env python3
"""
beats.py - раскладывает сценарий рилса по секундам ДО съёмки.

Считает, сколько займёт каждая строка вслух, ставит таймкоды и подсвечивает
четыре вещи, из-за которых зритель уходит: хук длиннее 3 секунд, кадр,
который висит дольше 4 секунд, подряд идущие строки без единой конкретики
(цифры, имени, суммы) и конец, который не возвращается к началу.

Время - оценка по числу слов и скорости речи (по умолчанию 140 слов в минуту,
для русского это нормально). Засеките, как вы читаете сценарий вслух, и
подставьте свою скорость через --wpm. Это план монтажа, а не замена записи.

Основа: beats.py из репозитория Jakeschincariol/instagram-agent-skill (MIT),
переделан под русский язык. Ничего не качает, не пишет на диск, только читает
файл, который вы ему дали.

Запуск
  python3 beats.py script.txt
  python3 beats.py script.txt --target 30
  python3 beats.py script.txt --wpm 150 --target 35
  pbpaste | python3 beats.py -
  python3 beats.py script.txt --json
"""

import argparse
import json
import re
import sys

WORD_RE = re.compile(r"[\w$%'’-]+")
SENT_RE = re.compile(r"[^.!?]+[.!?]*")
# число, сумма или имя с заглавной буквы не в начале предложения
CONCRETE_RE = re.compile(
    r"\d"
    r"|(?<!^)(?<![.!?]\s)\b[A-ZА-ЯЁ][a-zа-яё]{2,}\b",
    re.MULTILINE,
)
# суммы словами: «тысяча», «миллион», «рублей»
MONEY_WORDS_RE = re.compile(
    r"\b(?:тысяч\w*|миллион\w*|миллиард\w*|рубл\w*|процент\w*|долляр\w*|сотн\w*|десятк\w*)\b",
    re.IGNORECASE,
)
STOPWORDS = {
    "и", "а", "но", "или", "если", "что", "чтобы", "как", "это", "этот", "эта",
    "эти", "в", "на", "с", "со", "к", "по", "из", "у", "о", "об", "от", "до",
    "за", "для", "при", "не", "ни", "то", "так", "же", "ли", "бы", "вот",
    "я", "ты", "вы", "мы", "он", "она", "они", "мой", "твой", "ваш", "наш",
    "мне", "тебе", "вам", "нам", "меня", "тебя", "вас", "нас", "все", "всё",
    "весь", "один", "одна", "ещё", "уже", "там", "тут", "здесь", "есть",
    "был", "была", "было", "были", "будет", "можно", "надо", "нужно", "очень",
    "просто", "короче", "потом", "тоже", "даже", "только", "когда", "где",
}

HOOK_WINDOW = 3.0   # секунды. Дальше зритель уже решил, смотреть или листать.
MAX_BEAT = 4.0      # секунды на одну мысль без смены картинки.
ABSTRACT_RUN = 3    # строк подряд без конкретики.


def words(text):
    # "18 000" и "18,000" вслух - одно число, считаем одним словом
    text = re.sub(r"(?<=\d)[  ,](?=\d{3}\b)", "", text)
    return WORD_RE.findall(text)


def stem(word):
    """Грубая основа слова, чтобы 'долги' и 'долгов' считались одним словом."""
    w = word.lower().replace("ё", "е")
    return w[:5] if len(w) > 5 else w


def concrete_count(text):
    return len(CONCRETE_RE.findall(text)) + len(MONEY_WORDS_RE.findall(text))


def pretty(token):
    """Вернуть пробел в тысячах для показа: 180000 -> 180 000."""
    return re.sub(r"(\d)(?=(\d{3})+$)", r"\1 ", token)


def tc(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def split_beats(raw, wps):
    """Одна строка - один бит, если только строка не слишком длинная."""
    beats = []
    for line in [l.strip() for l in raw.splitlines()]:
        if not line:
            continue
        if len(words(line)) / wps <= MAX_BEAT * 1.5:
            beats.append(line)
            continue
        # Длинный абзац режем по концам предложений, чтобы тайминги что-то значили
        parts = [p.strip() for p in SENT_RE.findall(line) if p.strip()]
        buf = ""
        for part in parts:
            candidate = (buf + " " + part).strip()
            if buf and len(words(candidate)) / wps > MAX_BEAT:
                beats.append(buf)
                buf = part
            else:
                buf = candidate
        if buf:
            beats.append(buf)
    return beats


def analyse(raw, wpm=140, target=None):
    wps = wpm / 60.0
    beats = split_beats(raw, wps)
    if not beats:
        return None

    rows, clock = [], 0.0
    for i, text in enumerate(beats):
        n = len(words(text))
        dur = n / wps
        rows.append({
            "n": i + 1,
            "start": round(clock, 2),
            "dur": round(dur, 2),
            "words": n,
            "text": text,
            "concrete": concrete_count(text),
            "label": "",
            "flags": [],
        })
        clock += dur
    total = clock

    # Отмечаем места, на которых держится рилс
    for r in rows:
        if r["n"] == 1 or r["start"] + r["dur"] <= HOOK_WINDOW:
            r["label"] = "ХУК"
    rows[-1]["label"] = "CTA" if rows[-1]["label"] != "ХУК" else "ХУК/CTA"
    half = total / 2
    for r in rows:
        if not r["label"] and r["start"] <= half < r["start"] + r["dur"]:
            r["label"] = "СЕРЕДИНА"

    notes = []
    if rows[0]["dur"] > HOOK_WINDOW:
        rows[0]["flags"].append(f"хук идёт {rows[0]['dur']:.1f} с, дольше {HOOK_WINDOW:.0f} с")
        notes.append(f"Первую строку говорить {rows[0]['dur']:.1f} с. Сократите до "
                     f"{int(HOOK_WINDOW * wps)} слов или меньше, иначе зритель решит "
                     "листать раньше, чем хук договорится.")
    if rows[0]["concrete"] == 0:
        notes.append("В первой строке нет ни цифры, ни имени, ни суммы. Хуки, "
                     "в которых нечего проверить, чаще всего пролистывают.")

    for r in rows:
        if r["dur"] > MAX_BEAT:
            r["flags"].append(f"{r['dur']:.1f} с на одну строку")
    long_beats = [r["n"] for r in rows if r["dur"] > MAX_BEAT]
    if long_beats:
        notes.append(f"Слишком длинные строки (номера: {', '.join(map(str, long_beats))}), больше {MAX_BEAT:.0f} с. "
                     "Разбейте их или поменяйте картинку прямо внутри строки: "
                     "на неподвижном кадре люди уходят.")

    run, start = 0, None
    for r in rows:
        if r["concrete"] == 0:
            run += 1
            start = start if start is not None else r["n"]
            if run == ABSTRACT_RUN:
                notes.append(f"В строках {start}-{r['n']} нет ничего конкретного. "
                             "Добавьте в одну из них цифру, имя или сумму.")
        else:
            run, start = 0, None

    # Возвращает ли последняя строка к первой?
    first = {stem(w): w for w in words(rows[0]["text"]) if w.lower() not in STOPWORDS}
    last = {stem(w): w for w in words(rows[-1]["text"]) if w.lower() not in STOPWORDS}
    loop = sorted(pretty(first[k]) for k in first.keys() & last.keys())
    if len(rows) > 1 and loop:
        notes.append(f"Есть петля: последняя строка повторяет «{', '.join(loop[:3])}» из хука. "
                     "Повторный просмотр - бесплатный охват.")
    elif len(rows) > 1:
        notes.append("Петли нет. Последняя строка не делит с хуком ни одного слова, "
                     "ролик заканчивается ровно. Повторите одно слово из первой строки - "
                     "это самый дешёвый способ получить пересмотр.")

    if target:
        delta = total - target
        if abs(delta) <= target * 0.1:
            notes.append(f"Длина в цель ({total:.1f} с при цели {target:g} с).")
        elif delta > 0:
            notes.append(f"На {delta:.1f} с длиннее цели. Уберите около {int(delta * wps)} слов.")
        else:
            notes.append(f"На {-delta:.1f} с короче цели. Добавьте около {int(-delta * wps)} слов "
                         "или снимайте короче. Короче обычно лучше.")

    return {
        "wpm": wpm, "target": target,
        "total_seconds": round(total, 2),
        "total_words": sum(r["words"] for r in rows),
        "beats": rows,
        "notes": notes,
    }


def render(a, out=sys.stdout):
    head = (f"ТАЙМИНГ  |  {a['total_words']} слов  |  ~{a['total_seconds']:.1f} с "
            f"при {a['wpm']:g} слов/мин" + (f"  |  цель {a['target']:g} с" if a["target"] else ""))
    print("\n" + head, file=out)
    print("=" * max(len(head), 72), file=out)
    for r in a["beats"]:
        label = f"{r['label']:<9}" if r["label"] else " " * 9
        print(f"  {tc(r['start'])}  {r['dur']:4.1f} с  {label}{r['text']}", file=out)
        for f in r["flags"]:
            print(f"  {'':>6}  {'':>5}    {'':<9}^ {f}", file=out)
    print("-" * max(len(head), 72), file=out)
    for n in a["notes"]:
        print(f"  - {n}", file=out)
    print("", file=out)


def main():
    ap = argparse.ArgumentParser(description="Разложить сценарий рилса по секундам.")
    ap.add_argument("input", nargs="?", default="-", help="файл со сценарием или - для stdin")
    ap.add_argument("--wpm", type=float, default=140, help="скорость речи, слов в минуту (140)")
    ap.add_argument("--target", type=float, help="желаемая длина в секундах")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    result = analyse(raw, wpm=args.wpm, target=args.target)
    if result is None:
        print("Сценарий пустой.", file=sys.stderr)
        sys.exit(1)
    if args.json:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        print()
    else:
        render(result)


if __name__ == "__main__":
    main()
