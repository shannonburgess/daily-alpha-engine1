from pathlib import Path


WORKFLOW = Path(".github/workflows/diagnose-shadow-signal-coverage.yml")


def test_source_diagnostic_refreshes_aws_session_before_s3_publication():
    text = WORKFLOW.read_text()

    refresh = "- name: Refresh AWS credentials before sanitized publication"
    publish = "- name: Publish bounded sanitized evidence to staging"
    assert refresh in text
    assert publish in text
    assert text.index(refresh) < text.index(publish)

    refresh_block = text[text.index(refresh) : text.index(publish)]
    assert "uses: aws-actions/configure-aws-credentials@v5" in refresh_block
    assert "role-to-assume: arn:aws:iam::490809405132:role/DailyAlphaGitHubStagingDeployRole" in refresh_block
    assert "role-session-name: daily-alpha-sh24-source-publication" in refresh_block
    assert "aws-region: us-east-2" in refresh_block
    assert "unset-current-credentials: true" in refresh_block
    assert "github.ref == 'refs/heads/main'" in refresh_block
    assert "github.event_name != 'pull_request'" in refresh_block
