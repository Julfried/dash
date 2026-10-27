"""Finish-current/latest-pending scheduling over ordinary HTTP."""

from threading import Event, Lock
import time

import pytest

from dash import MATCH, Dash, Input, Output, State, ctx, dcc, html, no_update
from dash.exceptions import PreventUpdate
from dash.testing.wait import until


def test_latest_continuous_inputs_and_trigger_context(dash_duo):
    app = Dash(__name__)
    app.layout = html.Div(
        [
            dcc.Store(id="frame", data=0),
            dcc.Store(id="mode", data="original"),
            dcc.Store(id="state", data="original"),
            html.Div("ready", id="output"),
        ]
    )
    started, release = Event(), Event()
    lock = Lock()
    calls = []
    active = 0
    maximum_active = 0

    @app.callback(
        Output("output", "children"),
        Input("frame", "data"),
        Input("mode", "data"),
        State("state", "data"),
        prevent_initial_call=True,
        execution="latest",
    )
    def render(frame, mode, state):
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            calls.append(
                {
                    "frame": frame,
                    "mode": mode,
                    "state": state,
                    "triggers": list(ctx.triggered_prop_ids),
                }
            )
        try:
            if frame == 1:
                started.set()
                assert release.wait(10)
            time.sleep(0.1)
            return str(frame)
        finally:
            with lock:
                active -= 1

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#output", "ready")
    dash_duo.driver.execute_script(
        """
      window.previews=[];
      new MutationObserver(()=>previews.push({value:document.getElementById('output').textContent,time:performance.now()}))
        .observe(document.getElementById('output'),{childList:true,subtree:true,characterData:true});
      dash_clientside.set_props('frame',{data:1});
    """
    )
    until(started.is_set, timeout=5)
    try:
        dash_duo.driver.execute_script(
            """
          dash_clientside.set_props('state',{data:'latest'});
          dash_clientside.set_props('mode',{data:'new'});
          let frame=2;
          window.burst=setInterval(()=>{
            dash_clientside.set_props('frame',{data:frame++});
            if(frame>30){clearInterval(burst);window.burstEnd=performance.now();}
          },40);
        """
        )
        # Accumulate changes to both Inputs before the first computation finishes.
        time.sleep(0.2)
        release.set()
        dash_duo.wait_for_text_to_equal("#output", "30", timeout=10)
    finally:
        release.set()
    previews = dash_duo.driver.execute_script("return {frames:previews,end:burstEnd}")
    assert maximum_active == 1
    assert 2 < len(calls) < 30
    assert any(p["value"] == "1" for p in previews["frames"])
    assert any(p["time"] < previews["end"] for p in previews["frames"])
    assert calls[1]["mode"] == "new"
    assert calls[1]["state"] == "latest"
    assert set(calls[1]["triggers"]) == {"frame.data", "mode.data"}
    assert dash_duo.get_logs() == []


@pytest.mark.parametrize("outcome", ["no_update", "prevent_update", "error"])
def test_latest_releases_pending_after_terminal_result(dash_duo, outcome):
    app = Dash(__name__)
    app.layout = html.Div(
        [dcc.Store(id="input", data=0), html.Div("ready", id="output")]
    )
    started, release = Event(), Event()

    @app.callback(
        Output("output", "children"),
        Input("input", "data"),
        prevent_initial_call=True,
        execution="latest",
    )
    def render(value):
        if value == 1:
            started.set()
            assert release.wait(10)
            if outcome == "prevent_update":
                raise PreventUpdate
            if outcome == "error":
                raise ValueError("Intentional latest scheduling test failure")
            return no_update
        return str(value)

    dash_duo.start_server(app)
    dash_duo.driver.execute_script("dash_clientside.set_props('input',{data:1})")
    until(started.is_set, timeout=5)
    try:
        dash_duo.driver.execute_script("dash_clientside.set_props('input',{data:2})")
        time.sleep(0.1)
        release.set()
        dash_duo.wait_for_text_to_equal("#output", "2")
    finally:
        release.set()
    if outcome != "error":
        assert dash_duo.get_logs() == []


def test_latest_releases_after_failed_fetch(dash_duo):
    app = Dash(__name__)
    app.layout = html.Div(
        [dcc.Store(id="input", data=0), html.Div("ready", id="output")]
    )

    @app.callback(
        Output("output", "children"),
        Input("input", "data"),
        prevent_initial_call=True,
        execution="latest",
    )
    def render(value):
        return str(value)

    dash_duo.start_server(app)
    dash_duo.driver.execute_script(
        """
      const original=window.fetch;
      window.fetch=function(...args){
        if(String(args[0]).includes('_dash-update-component') && !window.failedFetch){
          window.failedFetch=true;return Promise.reject(new TypeError('Intentional failed fetch'));
        }
        return original.apply(this,args);
      };
      dash_clientside.set_props('input',{data:1});
    """
    )
    until(
        lambda: dash_duo.driver.execute_script("return !!window.failedFetch"), timeout=5
    )
    dash_duo.driver.execute_script("dash_clientside.set_props('input',{data:2})")
    dash_duo.wait_for_text_to_equal("#output", "2")


def test_latest_reads_state_after_applying_previous_result(dash_duo):
    app = Dash(__name__)
    app.layout = html.Div(
        [
            dcc.Store(id="input", data=0),
            dcc.Store(id="result", data=0),
            html.Div(id="output"),
        ]
    )
    started, release = Event(), Event()

    @app.callback(
        Output("result", "data"),
        Input("input", "data"),
        State("result", "data"),
        prevent_initial_call=True,
        execution="latest",
    )
    def accumulate(value, previous):
        if value == 1:
            started.set()
            assert release.wait(10)
        return previous + value

    app.clientside_callback(
        "value => String(value)", Output("output", "children"), Input("result", "data")
    )
    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#output", "0")
    dash_duo.driver.execute_script("dash_clientside.set_props('input',{data:1})")
    until(started.is_set, timeout=5)
    try:
        dash_duo.driver.execute_script("dash_clientside.set_props('input',{data:2})")
        time.sleep(0.1)
        release.set()
        dash_duo.wait_for_text_to_equal("#output", "3")
    finally:
        release.set()
    assert dash_duo.get_logs() == []


def test_latest_preserves_newer_self_input_while_publishing_preview(dash_duo):
    app = Dash(__name__)
    app.layout = html.Div([dcc.Input(id="input", value="0"), html.Div(id="preview")])
    started, release = Event(), Event()
    calls = []

    @app.callback(
        Output("input", "value"),
        Output("preview", "children"),
        Input("input", "value"),
        prevent_initial_call=True,
        execution="latest",
    )
    def render(value):
        calls.append(value)
        if value == "1":
            started.set()
            assert release.wait(10)
            return "stale", "first"
        return "accepted", "second"

    dash_duo.start_server(app)
    dash_duo.driver.execute_script(
        """
      window.previews=[];
      new MutationObserver(()=>previews.push(document.getElementById('preview').textContent))
        .observe(document.getElementById('preview'),{childList:true,subtree:true,characterData:true});
      dash_clientside.set_props('input',{value:'1'});
    """
    )
    until(started.is_set, timeout=5)
    try:
        dash_duo.driver.execute_script("dash_clientside.set_props('input',{value:'2'})")
        time.sleep(0.1)
        release.set()
        dash_duo.wait_for_text_to_equal("#preview", "second")
    finally:
        release.set()
    assert calls == ["1", "2"]
    assert "first" in dash_duo.driver.execute_script("return previews")
    assert dash_duo.find_element("#input").get_attribute("value") == "accepted"
    assert dash_duo.get_logs() == []


def test_latest_is_independent_per_pattern_instance(dash_duo):
    app = Dash(__name__)
    app.layout = html.Div(
        [dcc.Store(id={"type": "input", "index": i}, data=0) for i in range(2)]
        + [html.Div("ready", id={"type": "output", "index": i}) for i in range(2)]
    )
    started, release = Event(), Event()

    @app.callback(
        Output({"type": "output", "index": MATCH}, "children"),
        Input({"type": "input", "index": MATCH}, "data"),
        prevent_initial_call=True,
        execution="latest",
    )
    def render(value):
        if value == 1:
            started.set()
            assert release.wait(10)
        return str(value)

    dash_duo.start_server(app)
    dash_duo.driver.execute_script(
        "dash_clientside.set_props({type:'input',index:0},{data:1})"
    )
    until(started.is_set, timeout=5)
    try:
        dash_duo.driver.execute_script(
            "dash_clientside.set_props({type:'input',index:1},{data:2})"
        )
        selector = '[id=\'{"index":1,"type":"output"}\']'
        dash_duo.wait_for_text_to_equal(selector, "2")
    finally:
        release.set()
    dash_duo.wait_for_text_to_equal('[id=\'{"index":0,"type":"output"}\']', "1")
    assert dash_duo.get_logs() == []


def test_latest_discards_pending_work_when_output_is_removed(dash_duo):
    app = Dash(__name__, suppress_callback_exceptions=True)

    def children():
        return [dcc.Store(id="input", data=0), html.Div("ready", id="output")]

    app.layout = html.Div(
        [dcc.Store(id="mounted", data=True), html.Div(children(), id="host")]
    )
    started, release = Event(), Event()
    calls = []

    @app.callback(
        Output("host", "children"), Input("mounted", "data"), prevent_initial_call=True
    )
    def mount(mounted):
        return children() if mounted else []

    @app.callback(
        Output("output", "children"),
        Input("input", "data"),
        prevent_initial_call=True,
        execution="latest",
    )
    def render(value):
        calls.append(value)
        if value == 1:
            started.set()
            assert release.wait(10)
        return str(value)

    dash_duo.start_server(app)
    dash_duo.wait_for_text_to_equal("#output", "ready")
    dash_duo.driver.execute_script("dash_clientside.set_props('input',{data:1})")
    until(started.is_set, timeout=5)
    try:
        dash_duo.driver.execute_script("dash_clientside.set_props('input',{data:2})")
        time.sleep(0.1)
        dash_duo.driver.execute_script(
            "dash_clientside.set_props('mounted',{data:false})"
        )
        until(lambda: not dash_duo.find_elements("#output"), timeout=5)
    finally:
        release.set()
    time.sleep(0.1)
    dash_duo.driver.execute_script("dash_clientside.set_props('mounted',{data:true})")
    dash_duo.wait_for_text_to_equal("#output", "ready")
    dash_duo.driver.execute_script("dash_clientside.set_props('input',{data:3})")
    dash_duo.wait_for_text_to_equal("#output", "3")
    assert 2 not in calls
    assert dash_duo.get_logs() == []
