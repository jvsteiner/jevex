from dataclasses import dataclass


@dataclass(frozen=True)
class Slot:
    name: str
    instruction: str
    json_value: bool = False


# Hand-authored content assignments: no function names or JSON schemas are sent to the LLM.
# This is deliberately a curated tool set, not an automatic schema-to-prompt translator.
RECIPES = {
    "documents.list_documents": [],
    "documents.search_documents": [
        Slot(
            "query",
            "Write a short search phrase for the requested information. Return only the phrase.",
        )
    ],
    "documents.read_document": [
        Slot("name", "")  # Filled by a Jev Choice over known filenames, never by the writer.
    ],
    "math.add": [
        Slot(
            "values",
            "Write the numbers to be added as a JSON array of numbers. Return only the array.",
            True,
        )
    ],
    "math.subtract": [
        Slot(
            "a",
            "Write the starting amount from which the requested deduction should be made. Return only a JSON number.",
            True,
        ),
        Slot(
            "b",
            "Write the amount to deduct from the starting amount. Return only a JSON number.",
            True,
        ),
    ],
    "math.multiply": [
        Slot(
            "values",
            "Copy only the factors for one required product, such as a quantity and its unit price. Do not include unrelated items, sums, or computed answers. Return only a JSON array of numbers.",
            True,
        )
    ],
    "math.divide": [
        Slot("a", "Write the numerator for the requested ratio. Return only a JSON number.", True),
        Slot(
            "b", "Write the denominator for the requested ratio. Return only a JSON number.", True
        ),
    ],
    "math.mean": [
        Slot(
            "values",
            "Copy the numbers whose arithmetic average is requested. Return only a JSON array of numbers.",
            True,
        )
    ],
    "calendar.today": [],
    "calendar.add_days": [
        Slot(
            "date",
            "Copy the starting date for the requested date offset in YYYY-MM-DD format. Return only the date.",
        ),
        Slot(
            "days",
            "Write the requested signed number of calendar days to offset the starting date. Return only a JSON integer.",
            True,
        ),
    ],
    "calendar.days_between": [
        Slot(
            "start",
            "Copy the beginning of the requested date interval in YYYY-MM-DD format. Return only the date.",
        ),
        Slot(
            "end",
            "Copy the end of the requested date interval in YYYY-MM-DD format. Return only the date.",
        ),
    ],
    "calendar.weekday": [
        Slot(
            "date",
            "Copy the date whose weekday is requested in YYYY-MM-DD format. Return only the date.",
        )
    ],
}
