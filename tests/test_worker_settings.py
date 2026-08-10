"""قراردادِ کلاس‌های تنظیماتِ ARQ: هر کلاس باید صفاتش را در `__dict__`ِ خودش داشته باشد.

چرا این تست وجود دارد: arq در `get_kwargs` فقط `settings_cls.__dict__` را
می‌خواند (`arq/worker.py:889` در ۰.۲۸) و `__dict__` صفاتِ **ارث‌بری‌شده را
ندارد**. پس یک `class X(WorkerSettings)`ِ ساده هیچ صفتی از پدر به arq نمی‌رساند
و ورکر با «at least one function or cron_job must be registered» در حلقهٔ کرش
می‌افتد — دقیقاً همان چیزی که `MasterDownloadWorkerSettings` را از کار انداخت و
هیچ دانلودی انجام نشد.

تست عمداً **کشفِ خودکار** است: هر کلاسِ تازه‌ای که در `app.worker` اضافه شود
خودبه‌خود پوشش می‌گیرد. arq اجرا نمی‌شود و به Redis وصل نمی‌شویم — `create_worker`
فقط شیء را می‌سازد.
"""
from __future__ import annotations

import inspect

import pytest
from arq.worker import Worker, create_worker, get_kwargs

from app import worker as W

# صفاتی که هر ورکرِ این پروژه باید واقعاً به arq برساند. `queue_name` عمداً
# این‌جا نیست: نبودنش یعنی صفِ پیش‌فرضِ arq، که برای `WorkerSettings` درست است.
REQUIRED = ("functions", "on_startup", "on_shutdown", "redis_settings",
            "max_jobs", "job_timeout", "keep_result")


def _settings_classes() -> list[type]:
    """هر کلاسِ تنظیماتِ ARQ که **در خودِ** `app.worker` تعریف شده."""
    return [obj for _, obj in inspect.getmembers(W, inspect.isclass)
            if obj.__module__ == W.__name__ and obj.__name__.endswith("WorkerSettings")]


def _own_functions(cls: type):
    """`functions`ی که arq واقعاً می‌بیند — یعنی فقط `__dict__`ِ خودِ کلاس."""
    return cls.__dict__.get("functions")


def test_the_discovery_actually_found_the_classes():
    """اگر کشف چیزی پیدا نکند، بقیهٔ تست‌ها بی‌صدا vacuous می‌شوند."""
    names = {c.__name__ for c in _settings_classes()}
    assert {"WorkerSettings", "ProcessingWorkerSettings",
            "DownloadWorkerSettings", "MasterDownloadWorkerSettings"} <= names


@pytest.mark.parametrize("cls", _settings_classes(), ids=lambda c: c.__name__)
def test_functions_is_in_the_class_own_dict(cls):
    """arq فقط `__dict__`ِ خودِ کلاس را می‌خواند، پس ارث‌بری کافی نیست."""
    funcs = _own_functions(cls)
    assert funcs, (
        f"{cls.__name__}.functions در `__dict__`ِ خودش نیست — arq آن را نمی‌بیند "
        f"و ورکر با «at least one function…» بالا نمی‌آید. "
        f"دکوراتورِ `_flatten_settings` را اضافه کن.")


@pytest.mark.parametrize("cls", _settings_classes(), ids=lambda c: c.__name__)
def test_no_arq_attribute_is_silently_lost(cls):
    """فقط `functions` مهم نیست.

    افتادنِ `redis_settings` بی‌صداتر و بدتر است: ورکر بالا می‌آید ولی به
    `localhost:6379` وصل می‌شود نه به Redisِ ما.
    """
    kw = get_kwargs(cls)
    missing = [k for k in REQUIRED if k not in kw]
    assert not missing, f"{cls.__name__} این صفات را به arq نمی‌رساند: {missing}"


@pytest.mark.parametrize("cls", _settings_classes(), ids=lambda c: c.__name__)
def test_the_worker_really_builds(cls):
    """اثباتِ نهایی با خودِ arq — همان مسیری که در تولید کرش می‌کرد."""
    w = create_worker(cls)
    assert w.functions, f"{cls.__name__} ورکری بدونِ تابع ساخت"


def test_each_settings_class_keeps_its_own_queue():
    """صف‌ها نباید با هم قاطی شوند (کپی‌پیستِ یک `queue_name` بی‌سروصداست)."""
    queues = {c.__name__: get_kwargs(c).get("queue_name", "arq:queue")
              for c in _settings_classes()}
    assert len(set(queues.values())) == len(queues), f"صفِ تکراری: {queues}"
    assert queues["MasterDownloadWorkerSettings"] == "arq:queue:dl:master"
    assert queues["DownloadWorkerSettings"] == "arq:queue:dl"
    assert queues["ProcessingWorkerSettings"] == "arq:queue:proc"


def test_the_inheriting_classes_have_a_base_worth_inheriting_from():
    """اثباتِ اینکه دکوراتور واقعاً باربر است، نه تزئین روی کلاسِ مسطح.

    بعد از اجرای `_flatten_settings` همه‌چیز در `__dict__`ِ خودِ کلاس است، پس
    دیگر نمی‌شود «صفتِ ارث‌بری‌شده» را از «صفتِ خودش» تفکیک کرد — به‌جایش این را
    می‌سنجیم که پدر واقعاً صفاتِ arqی دارد و ساب‌کلاس در MROاش نشسته؛ یعنی چیزی
    برای گم‌شدن هست. بازسازیِ خودِ باگ کارِ
    `test_an_undecorated_subclass_is_caught` است.
    """
    inheriting = [c for c in _settings_classes() if c.__bases__ != (object,)]
    assert inheriting, "هیچ ساب‌کلاسی نمانده — این تست را بازبینی کن"
    for cls in inheriting:
        base = cls.__bases__[0]
        assert base in cls.__mro__ and base is not object
        missing = [k for k in REQUIRED if k not in get_kwargs(base)]
        assert not missing, (
            f"پدرِ {cls.__name__} یعنی {base.__name__} خودش ناقص است: {missing}")


def test_an_undecorated_subclass_is_caught():
    """کنترلِ ضدِ vacuous: باگ را عمداً بساز و مطمئن شو تست می‌گیردش.

    بدونِ این، تست‌های بالا ممکن است به دلیلِ غلط سبز باشند. این‌جا **دقیقاً**
    همان اشتباهِ تولیدی بازسازی می‌شود، بعد با دکوراتور رفع می‌شود.
    """
    class Broken(W.DownloadWorkerSettings):        # بدونِ `@_flatten_settings`
        queue_name = "arq:queue:test:broken"

    assert _own_functions(Broken) is None, "بازسازیِ باگ شکست خورد"
    assert "functions" not in get_kwargs(Broken)
    assert "redis_settings" not in get_kwargs(Broken)
    with pytest.raises(RuntimeError, match="at least one function"):
        create_worker(Broken)

    fixed = W._flatten_settings(Broken)
    assert _own_functions(fixed), "دکوراتور `functions` را نیاورد"
    assert not [k for k in REQUIRED if k not in get_kwargs(fixed)]
    assert create_worker(fixed).queue_name == "arq:queue:test:broken", \
        "دکوراتور نباید مقدارِ خودِ کلاس را بازنویسی کند"


def test_the_decorator_does_not_override_the_class_own_values():
    """مقدارِ خودِ کلاس همیشه برنده است (وگرنه `max_jobs=2`ِ نودِ پردازش می‌پرید)."""
    assert get_kwargs(W.ProcessingWorkerSettings)["max_jobs"] == 2
    assert get_kwargs(W.WorkerSettings)["max_jobs"] == 4


def test_required_names_are_real_arq_arguments():
    """اگر arq روزی آرگومانی را حذف/تغییرِ نام دهد، این تست اول می‌شکند."""
    accepted = set(inspect.signature(Worker).parameters)
    assert set(REQUIRED) <= accepted, f"arq اینها را نمی‌پذیرد: {set(REQUIRED) - accepted}"
