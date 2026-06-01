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
    "/Equation/3/Polynomial/User-Selectable Polynomial/",
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


# (url, wrapper id rendered by the RadioSelect/CheckboxSelectMultiple widget)
GROUPED_FIELDS = [
    ("/Equation/2/Polynomial/2nd Order (Quadratic)/", "id_fittingTarget"),
    ("/Equation/2/Polynomial/2nd Order (Quadratic)/", "id_commaConversion"),
    ("/Equation/2/Polynomial/2nd Order (Quadratic)/", "id_graphSize"),
    ("/Equation/3/Polynomial/Full Quadratic/", "id_dataPointSize3D"),
    ("/Equation/3/Polynomial/Full Quadratic/", "id_animationSize"),
    ("/FunctionFinder__.__/2/", "id_extendedEquationTypes"),
    ("/FunctionFinder__.__/2/", "id_equationFamilyInclusion"),
    ("/FunctionFinder__.__/2/", "id_smoothnessExactOrMax"),
    ("/StatisticalDistributions/1/", "id_statisticalDistributionsSortBy"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("url,field_id", GROUPED_FIELDS)
def test_group_field_wrapped_in_fieldset_with_legend(client, url, field_id):
    soup = _interface_soup(client, url)
    wrapper = soup.find(id=field_id)
    assert wrapper is not None, f"{field_id} not rendered on {url}"
    fieldset = wrapper.find_parent("fieldset", class_="field-group")
    assert fieldset is not None, f"{field_id} not inside a fieldset.field-group"
    legend = fieldset.find("legend")
    assert legend is not None and legend.get_text(strip=True), f"{field_id} on {url}: fieldset has no non-empty legend"


# (url, single-control field id that must have a <label for>) — URLs verified to render each field.
LABELLED_SINGLE_FIELDS = [
    ("/Equation/2/Polynomial/2nd Order (Quadratic)/", "id_textDataEditor"),
    ("/Equation/2/UserDefinedFunction/UserDefinedFunction/", "id_udfEditor"),
    ("/FunctionFinder__.__/2/", "id_smoothnessControl2D"),
    ("/FunctionFinder__.__/3/", "id_smoothnessControl3D"),
    ("/Equation/2/Polynomial/User-Selectable Polynomial/", "id_polynomialOrderX2D"),
    ("/Equation/3/Polynomial/User-Selectable Polynomial/", "id_polynomialOrderX3D"),
    ("/Equation/3/Polynomial/User-Selectable Polynomial/", "id_polynomialOrderY3D"),
]


@pytest.mark.django_db
@pytest.mark.parametrize("url,field_id", LABELLED_SINGLE_FIELDS)
def test_single_control_has_label_for(client, url, field_id):
    soup = _interface_soup(client, url)
    control = soup.find(id=field_id)
    assert control is not None, f"{field_id} not rendered on {url}"
    assert control.name in LABELABLE, f"{field_id} is <{control.name}>, expected a single control"
    label = soup.find("label", attrs={"for": field_id})
    assert label is not None, f"no <label for='{field_id}'> on {url}"
