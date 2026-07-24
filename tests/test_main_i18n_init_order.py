# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

"""Issue #61: RSSApp.OnInit must initialize i18n before showing any UI text,
including the single-instance-already-running MessageBox. A real wx.App
single-instance race is impractical to exercise in a unit test, so this
guards the fix at the source level instead.
"""
import inspect

import main


def test_i18n_setup_precedes_single_instance_check_and_message():
    source = inspect.getsource(main.RSSApp.OnInit)

    i18n_pos = source.index("i18n.setup(")
    checker_pos = source.index("SingleInstanceChecker(")
    message_pos = source.index("BlindRSS is already running")

    assert i18n_pos < checker_pos, (
        "i18n.setup() must run before the single-instance check so the "
        "\"already running\" message is translated"
    )
    assert i18n_pos < message_pos
