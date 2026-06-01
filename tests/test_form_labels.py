"""Accessibility coverage for form-control labels across the interfaces.

Each form control is named either by a <label for=id> (single labelable
control: <select>/<input>/<textarea>) or by a <fieldset><legend> (Django
RadioSelect / CheckboxSelectMultiple, which render a non-labelable
<div id=...> wrapper). A <label for> aimed at a non-labelable element — e.g.
the RadioSelect wrapper <div> — is a dead association: no click-to-focus, no
screen-reader name. The guard below renders every interface and proves no such
dead association ships. The presence tests pin that each migrated control is
actually named.
"""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

# HTML elements a <label for> may legitimately target.
LABELABLE = {"input", "select", "textarea", "button", "meter", "output", "progress"}

# GET routes that render a form interface (LongRunningProcessView, GET path).
INTERFACE_URLS = [
    "/Equation/2/Polynomial/2nd Order (Quadratic)/",
    "/Equation/3/Polynomial/Full Quadratic/",
    "/CharacterizeData/2/",
    "/CharacterizeData/3/",
    "/FunctionFinder__.__/2/",
    "/StatisticalDistributions/1/",
]


def _interface_soup(client, url):
    response = client.get(url)
    assert response.status_code == 200, f"{url} did not render (status {response.status_code})"
    return BeautifulSoup(response.content, "html.parser")


@pytest.mark.django_db
@pytest.mark.parametrize("url", INTERFACE_URLS)
def test_no_label_for_points_at_nonlabelable_element(client, url):
    soup = _interface_soup(client, url)
    offenders = []
    for label in soup.find_all("label", attrs={"for": True}):
        target_id = label["for"]
        target = soup.find(id=target_id)
        if target is None:
            offenders.append(f"<label for='{target_id}'> -> no element with that id")
        elif target.name not in LABELABLE:
            offenders.append(f"<label for='{target_id}'> -> <{target.name}> (not labelable)")
    assert not offenders, f"{url}: dead label/for associations: {offenders}"
