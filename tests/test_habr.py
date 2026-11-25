import httpx

from src.bot.keyboards import PROFESSIONS, STACKS, habr_query_params
from src.habr_client import HABR_VACANCIES_URL, HabrClient, parse_vacancy
from src.sources import HABR, HH, source_of

# Сокращённый элемент list[] из ответа /api/frontend/vacancies (снят 25.11.2026).
RAW_VACANCY = {
    "id": 1000170622,
    "href": "/vacancies/1000170622",
    "title": "Middle Backend-разработчик (Python/Django)",
    "company": {"id": 1000138495, "title": "ТЛ Групп"},
    "salary": {"from": None, "to": None, "currency": None, "formatted": ""},
    "predictedSalary": {"formatted": "от 190 000 до 300 000 ₽"},
    "qualification": "Middle",
    "locations": [{"title": "Москва", "href": "/vacancies?city_id=678"}],
}


def test_query_params_full_preset() -> None:
    assert habr_query_params("backend", "python", "between3And6", "1") == [
        [("s[]", 2), ("qid[]", 4), ("qid[]", 5), ("city_id", 678), ("skills[]", 446)]
    ]


def test_query_params_any_stack_grade_and_russia_add_no_filters() -> None:
    assert habr_query_params("qa", "any", None, "113") == [[("s[]", 12), ("s[]", 10)]]


def test_query_params_split_alternative_skills_into_requests() -> None:
    assert habr_query_params("frontend", "js", None, "2") == [
        [("s[]", 3), ("city_id", 679), ("skills[]", 264)],
        [("s[]", 3), ("city_id", 679), ("skills[]", 245)],
    ]


def test_query_params_skip_unknown_profession() -> None:
    assert habr_query_params("unknown", "python", None, "1") == []


def test_every_profession_and_stack_is_mapped() -> None:
    for profession in PROFESSIONS:
        assert habr_query_params(profession, "any", None, "113"), profession
    for stack in STACKS:
        params = habr_query_params("backend", stack, None, "113")
        has_skill = any(key == "skills[]" for key, _ in params[0])
        assert has_skill == (stack != "any"), stack


def test_parse_vacancy() -> None:
    assert parse_vacancy(RAW_VACANCY) == {
        "id": "habr:1000170622",
        "name": "Middle Backend-разработчик (Python/Django)",
        "employer": {"name": "ТЛ Групп"},
        "alternate_url": "https://career.habr.com/vacancies/1000170622",
        "salary": None,  # прогноз Хабра (predictedSalary) за зарплату не выдаём
        "source": HABR,
    }


def test_parse_vacancy_with_salary_and_without_company() -> None:
    raw = {"id": 7, "title": "QA", "company": None, "salary": {"formatted": "до 150 000 ₽"}}
    item = parse_vacancy(raw)
    assert item["salary"] == "до 150 000 ₽"
    assert item["employer"] == {"name": None}


def test_parse_vacancy_skips_broken_items() -> None:
    assert parse_vacancy({"title": "без id"}) is None
    assert parse_vacancy({"id": 1}) is None


def test_source_of() -> None:
    assert source_of("habr:1000170622") == HABR
    assert source_of("123456789") == HH


async def test_search_merges_requests_without_duplicates() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        skill = request.url.params["skills[]"]
        own = {**RAW_VACANCY, "id": int(skill), "title": f"Вакансия {skill}"}
        return httpx.Response(200, json={"list": [RAW_VACANCY, own], "meta": {}})

    client = HabrClient(transport=httpx.MockTransport(handler))
    try:
        data = await client.search_vacancies(habr_query_params("frontend", "js", None, "1"))
    finally:
        await client.close()

    assert [item["id"] for item in data["items"]] == [
        "habr:1000170622",
        "habr:264",
        "habr:245",
    ]
    assert len(requests) == 2
    first = requests[0].url
    assert str(first).startswith(HABR_VACANCIES_URL)
    assert first.params["sort"] == "date"
    assert first.params.get_list("s[]") == ["3"]
    assert first.params["city_id"] == "678"
