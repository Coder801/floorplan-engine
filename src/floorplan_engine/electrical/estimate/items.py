"""Electrical estimate items: the catalogue of what the estimate counts and in which section.

LINES has each item's section, unit and name (ru, uk); HINTS the item notes; keys with a parameter
(PARAM_KEYS: cable.<type>, frame.<posts>, work.chase.<material>…) are split by split_key; RETIRED
are the keys an old price list may still name.

Work comes in two sections with their own totals (decision 2026-11-03): rough (`rough`),
before plaster and screed: chases, passes and their sleeves, laying cable and conduit, flush
boxes, boxes with crimping, panel recess and enclosure, labelling, insulation test; finishing
(`finish`), after the finish: filling the panel with devices, panel labels, fitting the
devices, protection test. Materials are split the same way (decision 2026-11-13), by the work
they are bought for: rough (`material_rough`: cable, conduit and fixings, pass sleeves and
firestop foam, flush and junction boxes, crimps, enclosures, rough light) and finish
(`material_finish`: panel devices and comb busbars, wiring devices and frames, lights, outputs,
LED strip and supplies); Estimate.materials is both. An item's section is in LINES. Finish
materials are a bill of quantities without prices (LISTED_SECTIONS, decision 2026-11-27).
"""

from __future__ import annotations

import re
from typing import Literal

from floorplan_engine.model.panel_catalog import DeviceKind
from floorplan_engine.model.schema import WallMaterial

# Materials follow the work they are bought for (decision 2026-11-13): rough ones go in before
# the finishing of the room (cable, conduit, boxes, enclosures), finish ones after it (panel
# devices and busbars, wiring devices, lights). "material" is an estimate that is not split
# (plumbing)
Section = Literal["material", "material_rough", "material_finish", "rough", "finish"]
MATERIAL_SECTIONS: tuple[Section, ...] = ("material", "material_rough", "material_finish")
SECTIONS: tuple[Section, ...] = (*MATERIAL_SECTIONS, "rough", "finish")  # order in the estimate
# Sections that are a bill of quantities, never priced (decision 2026-11-27): finish materials —
# wiring devices, frames, lights, LED and all panel devices — depend on the series and brand the
# client picks, so the studio cannot know their price and an "average" one only misleads. Their
# rows carry the quantity only, the section has no total and stays out of the estimate total
LISTED_SECTIONS: tuple[Section, ...] = ("material_finish",)
WORK_PREFIX = "work."  # work items (services); the rest of LINES are materials

# Estimate items: key → section, unit, name (ru, uk). Keys with a parameter:
# cable.<type>, frame.<posts>, junction_box.<size>, junction_box_ip.<size>, panel devices
# <kind>.<rating> (breaker.C16); if there is no price with the parameter, the plain key is used
LINES: dict[str, tuple[Section, str, str, str]] = {
    "cable": ("material_rough", "м", "Кабель {mark}", "Кабель {mark}"),
    "conduit": ("material_rough", "м", "Гофротруба ПВХ Ø{n}", "Гофротруба ПВХ Ø{n}"),
    "conduit_joint": (
        "material_rough",
        "шт",
        "Муфта соединительная для гофры Ø{n}",
        "Муфта з'єднувальна для гофри Ø{n}",
    ),
    # Wall pass sleeves and their foam (sleeves.py, decision 2026-11-28)
    "sleeve": (
        "material_rough",
        "м",
        "Гильза ПВХ Ø{n} для прохода через стену",
        "Гільза ПВХ Ø{n} для проходу крізь стіну",
    ),
    "firestop_foam": (
        "material_rough",
        "шт",
        "Пена огнезащитная, баллон 325 мл",
        "Піна вогнезахисна, балон 325 мл",
    ),
    "socket_box": ("material_rough", "шт", "Подрозетник", "Підрозетник"),
    "junction_box": (
        "material_rough",
        "шт",
        "Коробка распаечная {mark}",
        "Коробка розподільча {mark}",
    ),
    "junction_box_ip": (
        "material_rough",
        "шт",
        "Коробка распаечная IP44 {mark}",
        "Коробка розподільча IP44 {mark}",
    ),
    "crimp": (
        "material_rough",
        "шт",
        "Гильза и термоусадка (опрессовка)",
        "Гільза і термоусадка (опресування)",
    ),
    "conduit_clip": (
        "material_rough",
        "шт",
        "Клипса для гофры Ø{n} с дюбель-гвоздём под монтажный пистолет",
        "Кліпса для гофри Ø{n} з дюбель-цвяхом під монтажний пістолет",
    ),
    "cable_pad": (
        "material_rough",
        "шт",
        "Площадка под монтажный пистолет с дюбель-гвоздём и стяжкой",
        "Площадка під монтажний пістолет з дюбель-цвяхом і стяжкою",
    ),
    "board_enclosure": ("material_rough", "шт", "Корпус щита", "Корпус щита"),
    # Panel devices by kind (DeviceKind); the row has the name and rating from the panel set
    "breaker": ("material_finish", "шт", "Автомат 1P (на группу)", "Автомат 1P (на групу)"),
    "diff": ("material_finish", "шт", "Дифавтомат 1P+N", "Дифавтомат 1P+N"),
    "rcd": ("material_finish", "шт", "УЗО", "ПЗВ"),
    "input": ("material_finish", "шт", "Вводной автомат", "Вступний автомат"),
    "relay": ("material_finish", "шт", "Реле напряжения", "Реле напруги"),
    "spd": ("material_finish", "шт", "УЗИП", "ПЗІП"),
    "changeover": ("material_finish", "шт", "Переключатель резерва", "Перемикач резерву"),
    "ats": ("material_finish", "шт", "АВР", "АВР"),
    "contactor": ("material_finish", "шт", "Контактор модульный", "Контактор модульний"),
    "feed": ("material_finish", "шт", "Автомат питания инвертора", "Автомат живлення інвертора"),
    "output": ("material_finish", "шт", "Автомат выхода инвертора", "Автомат виходу інвертора"),
    "dc_battery": ("material_finish", "шт", "Автомат АКБ DC", "Автомат АКБ DC"),
    "dc_breaker": (
        "material_finish",
        "шт",
        "Автомат строки панелей DC",
        "Автомат рядка панелей DC",
    ),
    "dc_spd": ("material_finish", "шт", "УЗИП DC", "ПЗІП DC"),
    # Comb busbar over a group rail, by poles (busbar.1P); a 1 m bar (panel.busbars)
    "busbar": (
        "material_finish",
        "шт",
        "Шина гребенчатая {mark}, 1 м",
        "Шина гребінчаста {mark}, 1 м",
    ),
    "dc_enclosure": ("material_rough", "шт", "Корпус щита АКБ", "Корпус щита АКБ"),
    "led_enclosure": (
        "material_rough",
        "шт",
        "Корпус щита блоков питания LED",
        "Корпус щита блоків живлення LED",
    ),
    "socket": ("material_finish", "шт", "Розетка с заземлением", "Розетка із заземленням"),
    "switch1": ("material_finish", "шт", "Выключатель одноклавишный", "Вимикач одноклавішний"),
    "switch2": ("material_finish", "шт", "Выключатель двухклавишный", "Вимикач двоклавішний"),
    "pass_switch": ("material_finish", "шт", "Выключатель проходной", "Вимикач прохідний"),
    "data": ("material_finish", "шт", "Розетка интернет", "Розетка інтернет"),
    "tv": ("material_finish", "шт", "Розетка TV", "Розетка TV"),
    "frame": ("material_finish", "шт", "Рамка {n}-постовая", "Рамка {n}-постова"),
    # Lights and outputs: names as in the legend (texts.symbol_*)
    "light": ("material_finish", "шт", "", ""),
    "downlight": ("material_finish", "шт", "", ""),
    "pendant": ("material_finish", "шт", "", ""),
    "sconce": ("material_finish", "шт", "", ""),
    "led_output": ("material_finish", "шт", "", ""),
    "outlet": ("material_finish", "шт", "", ""),
    # A finish material (no price, LISTED_SECTIONS); its work comes with the floor heating section
    "thermostat": ("material_finish", "шт", "", ""),
    "led_strip": ("material_finish", "м", "", ""),
    # Floor heating (floor_heating.py, decision 2026-11-14): by zones, priced by the studio list
    "heating_cable": (
        "material_rough",
        "шт",
        "Секция нагревательного кабеля {n} м",
        "Секція нагрівального кабелю {n} м",
    ),
    "heating_sensor": (
        "material_rough",
        "шт",
        "Датчик температуры пола",
        "Датчик температури підлоги",
    ),
    "heating_conduit": (
        "material_rough",
        "м",
        "Гофротруба Ø16 для датчика пола",
        "Гофротруба Ø16 для датчика підлоги",
    ),
    "led_psu": ("material_finish", "шт", "Блок питания LED 12 В", "Блок живлення LED 12 В"),
    "led_psu_din": (
        "material_finish",
        "шт",
        "Блок питания LED 12 В на DIN-рейку",
        "Блок живлення LED 12 В на DIN-рейку",
    ),
    "rough_holder": ("material_rough", "шт", "Патрон E27 черновой", "Патрон E27 чорновий"),
    "rough_lamp": ("material_rough", "шт", "Лампа LED E27 черновая", "Лампа LED E27 чорнова"),
    "rough_switch": ("material_rough", "шт", "Выключатель черновой", "Вимикач чорновий"),
    "work.cable": ("rough", "м", "Прокладка кабеля", "Прокладання кабелю"),
    "work.conduit": ("rough", "м", "Укладка кабеля в гофротрубу", "Укладання кабелю в гофротрубу"),
    "work.chase": (
        "rough",
        "м",
        "Штроба узкая, 1–2 кабеля",
        "Штроба вузька, 1–2 кабелі",
    ),
    "work.chase_wide": (
        "rough",
        "м",
        "Штроба широкая, 3–4 кабеля",
        "Штроба широка, 3–4 кабелі",
    ),
    # One pass — one sleeve (decision 2026-11-28): drilling, the sleeve, the firestop foam
    "work.cable_pass": ("rough", "шт", "Кабельная проходка", "Кабельний прохід"),
    "work.socket_box": (
        "rough",
        "шт",
        "Сверление и установка подрозетника",
        "Свердління і встановлення підрозетника",
    ),
    "work.junction_box": (
        "rough",
        "шт",
        "Монтаж коробки с опрессовкой",
        "Монтаж коробки з опресуванням",
    ),
    "work.splice": (
        "rough",
        "шт",
        "Соединение N и PE в подрозетнике выключателя",
        "З'єднання N і PE в підрозетнику вимикача",
    ),
    "work.splice_crimp": (
        "rough",
        "шт",
        "Соединение N и PE в подрозетнике выключателя опрессовкой",
        "З'єднання N і PE в підрозетнику вимикача опресуванням",
    ),
    "work.board_install": ("rough", "шт", "Установка щита", "Встановлення щита"),
    "work.board_module": ("finish", "мод.", "Сборка щита", "Збирання щита"),
    "work.panel_labels": (
        "finish",
        "щит",
        "Маркировка аппаратов щита наклейками",
        "Маркування апаратів щита наліпками",
    ),
    "work.mechanism": ("finish", "шт", "Установка механизмов", "Встановлення механізмів"),
    "work.led_psu": (
        "finish",
        "шт",
        "Установка и подключение блока питания LED у ленты",
        "Встановлення і підключення блока живлення LED біля стрічки",
    ),
    "work.led_psu_din": (
        "finish",
        "шт",
        "Установка и подключение блока питания LED в щите",
        "Встановлення і підключення блока живлення LED у щиті",
    ),
    "work.rough_light": (
        "rough",
        "шт",
        "Подключение чернового патрона с лампой к готовому выводу",
        "Підключення чорнового патрона з лампою до готового виводу",
    ),
    "work.rough_switch": (
        "rough",
        "шт",
        "Установка временного выключателя",
        "Встановлення тимчасового вимикача",
    ),
    "work.floor_heating": (
        "rough",
        "м²",
        "Укладка нагревательного кабеля змейкой с датчиком пола",
        "Укладання нагрівального кабелю змійкою з датчиком підлоги",
    ),
    "work.insulation_test": (
        "rough",
        "гр.",
        "Замер сопротивления изоляции с протоколом",
        "Вимірювання опору ізоляції з протоколом",
    ),
    "work.protection_test": (
        "finish",
        "гр.",
        "Проверка прибором дифавтоматов, УЗО и тока короткого замыкания с протоколом",
        "Перевірка приладом дифавтоматів, ПЗВ і струму короткого замикання з протоколом",
    ),
}
# Item notes: an "i" icon next to the name in the viewer, a comment in Excel; without a price
# also "price to be confirmed"
HINTS: dict[str, dict[str, str]] = {
    "work.mechanism": {
        "ru": "Установка розеток, выключателей, интернет- и ТВ-выводов",
        "uk": "Встановлення розеток, вимикачів, інтернет- і ТВ-виводів",
    },
    "conduit_clip": {
        "ru": "Крепление гофры к потолку, стенам и полу монтажным пистолетом",
        "uk": "Кріплення гофри до стелі, стін і підлоги монтажним пістолетом",
    },
    "cable_pad": {
        "ru": "Крепление кабеля без гофры к потолку и стенам монтажным пистолетом",
        "uk": "Кріплення кабелю без гофри до стелі та стін монтажним пістолетом",
    },
    "heating_cable": {
        "ru": "Двужильный, 18 Вт/м, холодный конец заводской; серия и ряд длин — допущение, "
        "уточнить по каталогу производителя",
        "uk": "Двожильний, 18 Вт/м, холодний кінець заводський; серія і ряд довжин — припущення, "
        "уточнити за каталогом виробника",
    },
    "heating_sensor": {
        "ru": "Обычно в комплекте регулятора",
        "uk": "Зазвичай у комплекті регулятора",
    },
    "work.floor_heating": {
        "ru": "По площади обогрева: раскладка по чертежу «Тёплый пол», гофра датчика, замеры",
        "uk": "За площею обігріву: розкладання за кресленням «Тепла підлога», гофра датчика, "
        "заміри",
    },
    "work.splice": {
        "ru": "По подрозетникам выключателей при свете цепочкой: у выключателя нет клемм N и "
        "PE, они (и фаза, если идёт дальше) соединяются в подрозетнике клеммами Wago; клеммы "
        "отдельной строкой не идут; в шлейфе розеток соединений нет",
        "uk": "За підрозетниками вимикачів при світлі ланцюжком: у вимикача немає клем N і PE, "
        "вони (і фаза, якщо йде далі) з'єднуються в підрозетнику клемами Wago; клеми окремим "
        "рядком не йдуть; у шлейфі розеток з'єднань немає",
    },
    "work.splice_crimp": {
        "ru": "По подрозетникам выключателей при свете цепочкой: N и PE (и фаза, если идёт "
        "дальше) опрессовываются гильзами с термоусадкой, гильзы отдельной строкой не идут; в "
        "тесном подрозетнике это сложнее, чем в коробке",
        "uk": "За підрозетниками вимикачів при світлі ланцюжком: N і PE (і фаза, якщо йде далі) "
        "опресовуються гільзами з термоусадкою, гільзи окремим рядком не йдуть; у тісному "
        "підрозетнику це складніше, ніж у коробці",
    },
    "sleeve": {
        "ru": "Гладкая жёсткая труба ПВХ; длина — толщина стены в месте прохода и по 10 мм "
        "выступа с каждой стороны",
        "uk": "Гладка жорстка труба ПВХ; довжина — товщина стіни в місці проходу і по 10 мм "
        "виступу з кожного боку",
    },
    "firestop_foam": {
        "ru": "Заделка зазоров в гильзах вокруг кабелей (ПУЭ п. 2.1.58): по объёму, выход "
        "баллона до 2,1 л — в тесной гильзе меньше",
        "uk": "Закладення зазорів у гільзах навколо кабелів (ПУЕ п. 2.1.58): за об'ємом, вихід "
        "балона до 2,1 л — у тісній гільзі менше",
    },
    "work.cable_pass": {
        "ru": "Сверление, гильза ПВХ на всю толщину стены с выступом 10 мм с каждой стороны, "
        "после протяжки кабелей — заделка огнезащитной пеной; кабели потом можно заменить",
        "uk": "Свердління, гільза ПВХ на всю товщину стіни з виступом 10 мм з кожного боку, "
        "після протягування кабелів — закладення вогнезахисною піною; кабелі потім можна "
        "замінити",
    },
    "busbar": {
        "ru": "Соединяет автоматы на рейке вместо перемычек; режется по месту",
        "uk": "З'єднує автомати на рейці замість перемичок; ріжеться за місцем",
    },
}
PARAM_KEYS = (
    "busbar",
    "heating_cable",
    "cable",
    "conduit",
    "conduit_clip",
    "conduit_joint",
    "frame",
    "junction_box",
    "junction_box_ip",
    "sleeve",
    "work.chase",
    "work.chase_wide",
    *(k.value for k in DeviceKind),
)
CHASE_KEYS = ("work.chase", "work.chase_wide")  # parameter: wall material
# Wall material in chase names, from the hardest one: the order of chase lines
WALL_MATERIALS: dict[WallMaterial, dict[str, str]] = {
    WallMaterial.CONCRETE: {"ru": "бетон", "uk": "бетон"},
    WallMaterial.CLAYDITE: {"ru": "керамзитобетон", "uk": "керамзитобетон"},
    WallMaterial.BRICK: {"ru": "кирпич", "uk": "цегла"},
    WallMaterial.AERATED: {"ru": "газоблок", "uk": "газоблок"},
}

# Lights and outputs: key → name in texts (as in the legend)
FIXTURES = {
    "light": "symbol_light",
    "downlight": "symbol_downlight",
    "pendant": "symbol_pendant",
    "sconce": "symbol_sconce",
    "led_output": "symbol_led_output",
    "outlet": "symbol_outlet",
    "thermostat": "symbol_thermostat",
    "led_strip": "legend_led_strip",
}


def split_key(key: str) -> tuple[str, str]:
    """Split "cable.3x1.5" → ("cable", "3x1.5"), "work.chase.brick" → ("work.chase", "brick");
    a key without a parameter → (key, "")."""
    head = WORK_PREFIX if key.startswith(WORK_PREFIX) else ""
    base, _, param = key[len(head) :].partition(".")
    return (head + base, param) if head + base in PARAM_KEYS and param else (key, "")


# Items folded into others: an old price list may still name them, the price is ignored
RETIRED = {
    "work.marking",  # cable end marking — part of work.cable since 2026-11-11
    # Drilling a pass and the core-drilled large hole: since 2026-11-28 a cable pass with a
    # sleeve and foam (work.cable_pass), several beside each other instead of a large one.
    # work.wall_hole stays a plumbing item (plumbing.estimate)
    "work.wall_hole",
    "work.wall_hole_large",
    "cable_fixing",  # split into conduit_clip.<Ø> and cable_pad on 2026-11-11
    # Wago clamps of switch flush boxes: not itemised since 2026-11-25 (in the joint work)
    "wago",
    "wago.412",
    "wago.413",
    "wago.415",
}


BARE_CABLE = re.compile(r"(\d+)\s*[xх×]\s*(\d+(?:[.,]\d+)?)")
DEFAULT_CABLE = "ВВГнг"  # power cable without a brand in the model


def cable_title(mark: str) -> str:
    """Cable in the estimate: a bare section gets the default brand ("3x6" → "ВВГнг 3×6"), as in
    the studio price list; a mark with its own brand ("ВВГнг-LS 3x2.5", "UTP cat.6") stays."""
    bare = BARE_CABLE.fullmatch(mark.strip())
    if bare is None:
        return mark
    return f"{DEFAULT_CABLE} {bare[1]}×{bare[2].replace('.', ',')}"
