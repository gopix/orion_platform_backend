from src.modules.accessibility_ppt.engine.ppt_validator.heading_agent import HeadingAgent


def test_placeholder_title_is_reported_as_fail():
    agent = HeadingAgent()
    context = {
        "slides": [
            {
                "title": "Click to add title",
                "shapes": [{"text": "Click to add title"}],
            }
        ]
    }

    issue = agent.run_check("PPT-HEADING-002", context)

    assert issue.rule_id == "PPT-HEADING-002"
    assert issue.status == "FAIL"
    assert "placeholder" in issue.message.lower()


def test_duplicate_slide_titles_are_reported():
    agent = HeadingAgent()
    context = {
        "slides": [
            {"title": "Overview", "shapes": [{"text": "Overview"}]},
            {"title": "Overview", "shapes": [{"text": "Overview"}]},
        ]
    }

    issue = agent.run_check("PPT-HEADING-003", context)

    assert issue.rule_id == "PPT-HEADING-003"
    assert issue.status == "FAIL"
    assert "duplicate" in issue.message.lower()
