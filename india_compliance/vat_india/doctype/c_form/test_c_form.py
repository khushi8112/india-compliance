# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import unittest

# test_records = frappe.get_test_records('C-Form')

IGNORE_TEST_RECORD_DEPENDENCIES = ["Company", "Customer", "Sales Invoice", "Territory"]


class TestCForm(unittest.TestCase):
    pass
