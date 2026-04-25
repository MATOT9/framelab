from framelab.runtime_tasks import RuntimeTaskController, RuntimeTaskState


def test_runtime_task_controller_tracks_active_and_latest_tasks() -> None:
    controller = RuntimeTaskController()

    first = controller.begin(
        "dataset_load:1",
        "Dataset load",
        target="scope-a",
        status="Loading",
        progress_done=2,
        progress_total=5,
    )
    assert first.state == RuntimeTaskState.RUNNING
    assert controller.active_tasks() == (first,)
    assert controller.summary_text() == "Dataset load - scope-a - Loading - 2/5"

    controller.begin("dynamic_stats:2", "Top-K compute", status="Checking cache")
    active = controller.active_tasks()
    assert [task.task_id for task in active] == ["dynamic_stats:2", "dataset_load:1"]
    assert controller.summary_text() == "Top-K compute - Checking cache (+1)"

    controller.finish("dynamic_stats:2", status="Complete")
    assert [task.task_id for task in controller.active_tasks()] == ["dataset_load:1"]

    controller.finish("dataset_load:1", status="Loaded 5 images")
    assert controller.active_tasks() == ()
    assert controller.summary_text() == ""
    assert controller.latest_task().status == "Loaded 5 images"


def test_runtime_task_controller_reports_failed_latest_task() -> None:
    controller = RuntimeTaskController()

    controller.begin("roi_apply:3", "ROI apply", status="Computing")
    controller.finish(
        "roi_apply:3",
        state=RuntimeTaskState.FAILED,
        status="Invalid ROI",
    )

    assert controller.active_tasks() == ()
    assert controller.summary_text() == "ROI apply - Invalid ROI"
