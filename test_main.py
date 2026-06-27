import sys
import unittest
from unittest.mock import MagicMock, patch

from PyQt5 import QtWidgets
from PyQt5.QtTest import QTest
from PyQt5.QtCore import Qt

# Import your application. 
# (Make sure your previous code is saved as main.py)
import main 

# We need one global QApplication instance for PyQt to work in tests
app = QtWidgets.QApplication(sys.argv)

class TestGUI(unittest.TestCase):
    """Tests the PyQt5 GUI methods in isolation (No Selenium required)"""

    def setUp(self):
        """Runs before every test: Creates a fresh UI instance."""
        self.ui = main.App()
        
        # Stop the worker immediately so it doesn't try to load browsers in the background
        self.ui.worker.terminate() 

    def test_toggles_logic(self):
        """Test if Random Gen and Manual Input properly toggle each other."""
        # Check Initial State
        self.assertTrue(self.ui.actionRandom_Gen.isChecked())
        self.assertFalse(self.ui.actionManual_Input.isChecked())
        
        # Toggle Manual ON
        self.ui.actionManual_Input.setChecked(True)
        self.assertTrue(self.ui.actionManual_Input.isChecked())
        self.assertFalse(self.ui.actionRandom_Gen.isChecked())

        # Toggle Random ON
        self.ui.actionRandom_Gen.setChecked(True)
        self.assertTrue(self.ui.actionRandom_Gen.isChecked())
        self.assertFalse(self.ui.actionManual_Input.isChecked())

    def test_update_status(self):
        """Test if the status label updates text and colors correctly."""
        self.ui.update_status("error", "Testing Error Color")
        self.assertEqual(self.ui.progressLabel.text(), "Testing Error Color")
        self.assertIn("#A11515", self.ui.progressLabel.styleSheet())

        self.ui.update_status("success", "Testing Success Color")
        self.assertEqual(self.ui.progressLabel.text(), "Testing Success Color")
        self.assertIn("#33AA33", self.ui.progressLabel.styleSheet())

    def test_populate_departments(self):
        """Test if the combo box fills correctly and enables the start button."""
        fake_depts = ["Select Dept", "BS CS", "BS Physics"]
        self.ui.populate_departments(fake_depts)
        
        self.assertEqual(self.ui.comboBox.count(), 3)
        self.assertEqual(self.ui.comboBox.itemText(1), "BS CS")
        self.assertTrue(self.ui.comboBox.isEnabled())
        self.assertTrue(self.ui.feedButton.isEnabled())

    @patch.object(main.SeleniumWorker, 'start')
    def test_start_autofeed_validation(self, mock_worker_start):
        """Test form validation before launching the bot."""
        # 1. Test empty department
        self.ui.comboBox.addItems(["Select Dept", "BS CS"])
        self.ui.comboBox.setCurrentIndex(0)
        self.ui.start_autofeed()
        self.assertEqual(self.ui.progressLabel.text(), "You must select a department")
        mock_worker_start.assert_not_called()

        # 2. Test empty credentials
        self.ui.comboBox.setCurrentIndex(1)
        self.ui.regNo.setText("")
        self.ui.start_autofeed()
        self.assertEqual(self.ui.progressLabel.text(), "Reg No and Access Code cannot be empty")
        mock_worker_start.assert_not_called()

        # 3. Test valid data triggers the worker thread
        self.ui.regNo.setText("12345")
        self.ui.access_code.setText("ABC")
        self.ui.start_autofeed()
        
        self.assertFalse(self.ui.feedButton.isEnabled())
        self.assertEqual(self.ui.worker.reg_no, "12345")
        self.assertEqual(self.ui.worker.access_code, "ABC")
        self.assertEqual(self.ui.worker.mode, "feed")
        mock_worker_start.assert_called_once()

    def test_contributor_ui_flow(self):
        """Test switching to the Contributor Selection page and back."""
        # Trigger the prompt
        self.ui.prompt_contributor("Physics 101", ["Teacher A", "Teacher B"])
        
        # Verify page changed to list widget
        self.assertEqual(self.ui.stackedWidget.currentWidget(), self.ui.page_2)
        self.assertEqual(self.ui.listWidget.count(), 2)
        
        # Simulate selecting row 1 (Teacher B) and clicking 'Select'
        self.ui.listWidget.setCurrentRow(1)
        self.ui.on_contributor_selected()
        
        # Verify state returned to normal and worker thread unpaused
        self.assertEqual(self.ui.stackedWidget.currentWidget(), self.ui.page)
        self.assertEqual(self.ui.worker.selected_idx, 1)
        self.assertTrue(self.ui.worker.wait_event.is_set())

    def test_manual_input_ui_flow(self):
        """Test switching to the Manual Rating page and back."""
        self.ui.prompt_manual("Physics 101", "Teacher A")
        
        self.assertEqual(self.ui.stackedWidget.currentWidget(), self.ui.page_3)
        self.assertIn("Physics 101", self.ui.mi_label.text())
        
        # Set spinbox to 4 and submit
        self.ui.mi_spinBox.setValue(4)
        self.ui.on_manual_submit()
        
        self.assertEqual(self.ui.stackedWidget.currentWidget(), self.ui.page)
        self.assertEqual(self.ui.worker.manual_val, 4)
        self.assertTrue(self.ui.worker.wait_event.is_set())


class TestSeleniumWorker(unittest.TestCase):
    """Tests the Selenium background worker isolated from real networks."""

    def setUp(self):
        self.worker = main.SeleniumWorker()
        # Create a completely fake browser
        self.worker.browser = MagicMock()

    @patch('main.Select')
    def test_init_browser_extracts_departments(self, MockSelect):
        """Tests if the initialization correctly reads departments off a dummy page."""
        # Mock check_element to instantly return a dummy element
        self.worker.check_element = MagicMock(return_value=MagicMock())
        
        # Mock the Select element to pretend it has 2 options
        opt1, opt2 = MagicMock(), MagicMock()
        opt1.text = "Dept 1"
        opt2.text = "Dept 2"
        MockSelect.return_value.options = [opt1, opt2]

        # Intercept the signal that would normally go to the GUI
        emitted_depts = []
        self.worker.signals.departments_ready.connect(lambda depts: emitted_depts.extend(depts))

        # We must override `get` and `skip_alert` so they do nothing
        self.worker.browser.get = MagicMock()
        self.worker.skip_alert = MagicMock()

        self.worker.init_browser()

        # Check if it properly grabbed the text from the mocked HTML options
        self.assertEqual(emitted_depts, ["Dept 1", "Dept 2"])

    @patch('main.Select')
    def test_login_flow_simulated(self, MockSelect):
        """Tests that login inputs are routed to the correct dummy DOM elements."""
        self.worker.reg_no = "MY_REG_NO"
        self.worker.access_code = "MY_CODE"
        self.worker.dept_index = 2      # Let's say we chose department index 2
        self.worker.is_regular = False  # Skip feedback logic for this test
        self.worker.is_detailed = False

        # Fake elements on the page
        fake_reg = MagicMock()
        fake_pass = MagicMock()
        fake_dept = MagicMock()
        
        def fake_check_element(element_id, wait=1):
            if element_id == "txtRegNo": return fake_reg
            if element_id == "a63542B5": return fake_pass
            if element_id == "ddlDegreeProg": return fake_dept
            return None
            
        self.worker.check_element = MagicMock(side_effect=fake_check_element)
        self.worker.skip_alert = MagicMock()

        # Catch the finished signal
        finished_flag = []
        self.worker.signals.feed_finished.connect(lambda: finished_flag.append(True))

        self.worker.run_feedback()

        # Validate that the bot successfully typed credentials into the fake DOM
        fake_reg.send_keys.assert_called_with("MY_REG_NO")
        # Ensure it pressed ENTER at the end of the password
        fake_pass.send_keys.assert_called_with("MY_CODE", main.Keys.RETURN)
        
        # Verify it selected the correct dropdown index!
        MockSelect.return_value.select_by_index.assert_called_with(2)

        # Verify it gracefully finished the routine
        self.assertTrue(finished_flag[0])
        
if __name__ == "__main__":
    unittest.main()