# Copyright (c) serrebidev and contributors
# This file is part of BlindRSS
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import MagicMock, patch
from core import utils

def test_get_chapters_batch_large_list():
    # Simulate a large list of IDs (e.g. 2500)
    ids = [f"id-{i}" for i in range(2500)]
    
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = []
    
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    
    with patch("core.utils.get_connection", return_value=mock_conn):
        utils.get_chapters_batch(ids)
        
        # Should have called execute 3 times (900 + 900 + 700)
        assert mock_cursor.execute.call_count == 3
        
        # Verify chunk sizes
        args_list = mock_cursor.execute.call_args_list
        
        # First call
        sql1, params1 = args_list[0][0]
        assert len(params1) == 900
        assert params1[0] == "id-0"
        assert params1[-1] == "id-899"
        
        # Second call
        sql2, params2 = args_list[1][0]
        assert len(params2) == 900
        assert params2[0] == "id-900"
        
        # Third call
        sql3, params3 = args_list[2][0]
        assert len(params3) == 700
        assert params3[-1] == "id-2499"

if __name__ == "__main__":
    test_get_chapters_batch_large_list()
