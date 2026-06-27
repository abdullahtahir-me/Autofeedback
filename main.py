import sys, os, time, random, threading, math
from PyQt5 import QtCore, QtGui, QtWidgets, uic

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import (TimeoutException, StaleElementReferenceException, 
                                        NoSuchElementException, ElementNotInteractableException)

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class WorkerSignals(QtCore.QObject):
    """Defines the signals available from a running worker thread to safely update GUI"""
    status = QtCore.pyqtSignal(str, str)
    progress = QtCore.pyqtSignal(int)
    departments_ready = QtCore.pyqtSignal(list)
    ask_contributor = QtCore.pyqtSignal(str, list)
    ask_manual_input = QtCore.pyqtSignal(str, str)
    ask_confirmation = QtCore.pyqtSignal(str, str)
    feed_finished = QtCore.pyqtSignal()


class SeleniumWorker(QtCore.QThread):
    def __init__(self):
        super().__init__()
        self.signals = WorkerSignals()
        self.browser = None
        self.mode = "init"
        
        # User Data
        self.reg_no = ""
        self.access_code = ""
        self.dept_index = 0
        self.is_regular = True
        self.is_detailed = False
        self.is_manual = False
        
        # Synchronization Events for mid-task UI popups
        self.wait_event = threading.Event()
        self.selected_idx = 0
        self.manual_val = 3
        self.user_confirmed = False

    def run(self):
        if self.mode == "init":
            self.init_browser()
        elif self.mode == "feed":
            self.run_feedback()

    def check_element(self, element_id, wait_time=10):
        try:
            return WebDriverWait(self.browser, wait_time).until(EC.visibility_of_element_located((By.ID, element_id)))
        except (StaleElementReferenceException, TimeoutException):
            return None

    def skip_alert(self, wait_time=3):
        try:
            WebDriverWait(self.browser, wait_time).until(EC.alert_is_present())
            self.browser.switch_to.alert.accept()
        except Exception:
            pass

    def init_browser(self):
        self.signals.status.emit("special", "Starting Webdriver..")
        
        # --- CRITICAL LINUX APPIMAGE FIX ---
        env_vars_to_clean = ['LD_LIBRARY_PATH', 'APPDIR', 'APPIMAGE']
        for var in env_vars_to_clean:
            if var in os.environ:
                del os.environ[var]
        
        try:
            # 1st Try: Microsoft Edge (Perfect for Windows users)
            self.browser = webdriver.Edge()
            self.signals.status.emit("success", "Opening Microsoft Edge..")
        except Exception as e_edge:
            try:
                # 2nd Try: Firefox (Perfect for Linux users)
                self.browser = webdriver.Firefox()
                self.signals.status.emit("success", "Opening Firefox..")
            except Exception as e_firefox:
                try:
                    # 3rd Try: Google Chrome (Universal Fallback)
                    self.browser = webdriver.Chrome()
                    self.signals.status.emit("success", "Opening Google Chrome..")
                except Exception as e_chrome:
                    # If all fail, output errors to console
                    print(f"Edge Error: {e_edge}")
                    print(f"Firefox Error: {e_firefox}")
                    print(f"Chrome Error: {e_chrome}")
                    self.signals.status.emit("error", "No supported browser found. See terminal.")
                    return

        # Navigate to portal to fetch initial dropdowns
        self.browser.get("http://111.68.99.200/SRA-n/")
        self.skip_alert(10)
        
        self.signals.status.emit("notify", "Fetching departments..")
        if (dept_elem := self.check_element("ddlDegreeProg")):
            depts = [opt.text for opt in Select(dept_elem).options]
            self.signals.departments_ready.emit(depts)
        else:
            self.signals.status.emit("error", "Failed to load departments. Site down?")

    def run_feedback(self):
        self.signals.status.emit("notify", "Initializing..")
        self.signals.progress.emit(0)
        self.browser.get("http://111.68.99.200/SRA-n/")
        self.skip_alert(5)
        
        if (elem := self.check_element("ddlDegreeProg")):
            Select(elem).select_by_index(self.dept_index)
        if (elem := self.check_element("txtRegNo")):
            elem.clear()
            elem.send_keys(self.reg_no)
        if (elem := self.check_element("a63542B5")):
            elem.clear()
            elem.send_keys(self.access_code, Keys.RETURN)
            
        self.skip_alert(5)
        
        try:
            self.browser.find_element(By.ID, "cmdViewTranscript")
        except NoSuchElementException:
            try:
                err_text = self.browser.find_element(By.ID, "lblMessage").text
                self.signals.status.emit("error", err_text)
            except NoSuchElementException:
                self.signals.status.emit("error", "Login failed.")
            self.signals.feed_finished.emit()
            return

        self.signals.status.emit("notify", "Opening Menu..")
        menu_url = "http://111.68.99.200/SRA-n/mainselcfrmx.aspx"
        count = 0
        while True:
            self.browser.get(menu_url)
            self.skip_alert(5)
            if self.browser.current_url == menu_url: break
            if count > 10:
                self.signals.status.emit("error", "Cannot reach main menu. Make sure dues are cleared.")
                self.signals.feed_finished.emit()
                return
            count += 1
            
        self.signals.status.emit("notify", "Opening Feedback Page..")
        self.browser.find_element(By.ID, "btnfeedback").send_keys(Keys.RETURN)
        
        if self.is_regular:
            self.do_regular_feedback()
        if self.is_detailed:
            self.do_detailed_feedback()
            
        self.signals.feed_finished.emit()

    def do_regular_feedback(self):
        self.signals.status.emit("success", "Starting regular feedback..")
        
        if not hasattr(self, 'course_teacher_map'):
            self.course_teacher_map = {}

        if not (course_ddl_el := self.check_element("_ctl0_ContentPlaceHolder1_ddlCourse")): return
        course_ddl = Select(course_ddl_el)
        
        # Check for dummy "Select" index
        start_idx = 1 if "select" in course_ddl.options[0].text.lower() else 0
        valid_indices = list(range(start_idx, len(course_ddl.options)))
        courses_len = len(valid_indices)
        
        if courses_len == 0:
            self.signals.status.emit("error", "No valid courses found to grade.")
            return

        completed = 0.0
        portion = 100.0 / courses_len
        sub_portion = portion / 17.0
        
        for name_idx in valid_indices:
            if not self.check_element("_ctl0_ContentPlaceHolder1_ddlCourse"): return
            Select(self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_ddlCourse")).select_by_index(name_idx)
            
            time.sleep(1) # Wait for page postback
            
            if not self.check_element("_ctl0_ContentPlaceHolder1_ddlContributor"): return
            contributor_ddl = Select(self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_ddlContributor"))
            contributors_texts = [opt.text for opt in contributor_ddl.options]
            
            course_name = Select(self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_ddlCourse")).options[name_idx].text
            self.signals.status.emit("success", f"Processing {course_name}..")
            
            teacher = self.course_teacher_map.get(course_name)
            
            if teacher:
                contributor_ddl.select_by_visible_text(teacher)
                time.sleep(0.5)
            else:
                if len(contributors_texts) > 2:
                    self.signals.ask_contributor.emit(course_name, contributors_texts[:-1])
                    self.wait_event.clear()
                    self.wait_event.wait()
                    
                    contributor_ddl = Select(self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_ddlContributor"))
                    contributor_ddl.select_by_index(self.selected_idx)
                    teacher = contributors_texts[self.selected_idx]
                else:
                    contributor_ddl.select_by_index(0)
                    teacher = contributors_texts[0]
                    
                self.course_teacher_map[course_name] = teacher
                time.sleep(0.5)
                
            if self.is_manual:
                self.signals.ask_manual_input.emit(course_name, teacher)
                self.wait_event.clear()
                self.wait_event.wait()
                
            for i in range(18):
                score_id = f"_ctl0_ContentPlaceHolder1_txt{chr(ord('A') + i)}"
                number = self.manual_val if self.is_manual else random.randrange(1, 6)
                
                if (el := self.check_element(score_id, wait_time=1)):
                    try:
                        el.clear()
                        el.send_keys(str(number))
                    except Exception: pass
                completed += sub_portion
                self.signals.progress.emit(int(math.ceil(completed)))
                
            if (el := self.check_element("_ctl0_ContentPlaceHolder1_txtComments")): el.send_keys("No Comment")
            if (el := self.check_element("_ctl0_ContentPlaceHolder1_txtCommentsCourse")): el.send_keys("No Comment")
            
            time.sleep(0.5)
            self.signals.ask_confirmation.emit(
                "Confirm Submit", 
                f"Please review the browser window.\n\nAre you ready to SUBMIT feedback for:\n{course_name}?"
            )
            self.wait_event.clear()
            self.wait_event.wait()
            
            if self.user_confirmed:
                if (el := self.check_element("_ctl0_ContentPlaceHolder1_cmdSubmit")): 
                    el.click()
                    self.signals.status.emit("notify", "Submitted. Waiting for refresh...")
                    time.sleep(1.5) 
                else:
                    return
            else:
                self.signals.status.emit("error", f"Skipped Submit for {course_name}")

            self.signals.ask_confirmation.emit(
                "Confirm Reset", 
                f"Do you want to click RESET to prepare for the next course?"
            )
            self.wait_event.clear()
            self.wait_event.wait()

            if self.user_confirmed:
                if (el := self.check_element("_ctl0_ContentPlaceHolder1_cmdReset")):
                    try: 
                        el.click()
                        time.sleep(1.5)
                    except ElementNotInteractableException:
                        self.signals.status.emit("error", "Feedback already submitted")
                        try:
                            self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_txtComments").clear()
                            self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_txtCommentsCourse").clear()
                        except Exception:
                            pass
                else:
                    return
            else:
                 self.signals.status.emit("error", f"Skipped Reset for {course_name}")
                
        self.signals.status.emit("success", "Regular feedback completed")


    def do_detailed_feedback(self):
        self.signals.status.emit("success", "Mapping teachers for detailed feedback..")
        
        if not hasattr(self, 'course_teacher_map'):
            self.course_teacher_map = {}

        if not (course_ddl_el := self.check_element("_ctl0_ContentPlaceHolder1_ddlCourse")): return
        course_ddl = Select(course_ddl_el)
        
        start_idx = 1 if "select" in course_ddl.options[0].text.lower() else 0
        valid_indices = list(range(start_idx, len(course_ddl.options)))
        
        for name_idx in valid_indices:
            if not self.check_element("_ctl0_ContentPlaceHolder1_ddlCourse"): return
            Select(self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_ddlCourse")).select_by_index(name_idx)
            
            time.sleep(1) # Wait for postback
            
            c_name = Select(self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_ddlCourse")).options[name_idx].text
            
            if c_name not in self.course_teacher_map:
                if not self.check_element("_ctl0_ContentPlaceHolder1_ddlContributor"): return
                contributor_ddl = Select(self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_ddlContributor"))
                contributors_texts = [opt.text for opt in contributor_ddl.options]
                
                if len(contributors_texts) > 2:
                    self.signals.ask_contributor.emit(c_name, contributors_texts[:-1])
                    self.wait_event.clear()
                    self.wait_event.wait()
                    
                    contributor_ddl = Select(self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_ddlContributor"))
                    contributor_ddl.select_by_index(self.selected_idx)
                    teacher = contributors_texts[self.selected_idx]
                else:
                    contributor_ddl.select_by_index(0)
                    teacher = contributors_texts[0]
                    
                self.course_teacher_map[c_name] = teacher
                time.sleep(0.5)

        self.signals.status.emit("success", "Entering detailed feedback section..")
        if (eval_btn := self.check_element("_ctl0_ContentPlaceHolder1_cmdCourseEvaluation2")):
            eval_btn.click() 
            time.sleep(2) 
        else:
            self.signals.status.emit("error", "Detailed Evaluation button not found.")
            return

        if not (course_ddl_el := self.check_element("_ctl0_ContentPlaceHolder1_ddlCourse")): return
        course_ddl = Select(course_ddl_el)
        
        target_idx = 1 if "select" in course_ddl.options[0].text.lower() else 0
        course_len = len(course_ddl.options) - target_idx
        
        if course_len <= 0:
            self.signals.status.emit("error", "All detailed feedbacks have already been submitted.")
            self.signals.progress.emit(100)
            return

        box_ids = ("A1","A2","A3","A4","B2","B3","B4","C1","C2","C3","C4","C5","D1","D2","D3",
                   "D4","D5","E1","E2","E3","E4","F1","F2","F3","F4","G1","G2","G3","G4","H1","H2","H3","I1","I2")
        
        completed = 25.0
        portion = (100.0 - completed) / course_len
        sub_portion = portion / len(box_ids)

        for i in range(course_len):
            if not self.check_element("_ctl0_ContentPlaceHolder1_ddlCourse"): return
            
            course_ddl = Select(self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_ddlCourse"))
            c_name = course_ddl.options[target_idx].text
            
            teacher = self.course_teacher_map.get(c_name, "Unknown Teacher")
            
            if self.is_manual:
                self.signals.ask_manual_input.emit(c_name, teacher)
                self.wait_event.clear()
                self.wait_event.wait()
                
            self.signals.status.emit("success", f"Generating detailed feedback for {c_name}..")

            Select(self.browser.find_element(By.ID, "_ctl0_ContentPlaceHolder1_ddlCourse")).select_by_index(target_idx)
            time.sleep(1)

            if (el := self.check_element("_ctl0_ContentPlaceHolder1_txtfnames")):
                el.clear()
                el.send_keys(teacher)
                
            if (el := self.check_element("_ctl0_ContentPlaceHolder1_txtB1")):
                el.clear()
                el.send_keys("5")

            for box in box_ids:
                if (current_el := self.check_element(f"_ctl0_ContentPlaceHolder1_txt{box}", wait_time=1)):
                    try:
                        current_el.clear()
                        if current_el.tag_name == "textarea":
                            current_el.send_keys("No comment")
                        else:
                            number = self.manual_val if self.is_manual else random.randrange(1, 6)
                            current_el.send_keys(str(number))
                    except Exception:
                        pass
                
                completed += sub_portion
                self.signals.progress.emit(int(math.ceil(completed)))
                
            time.sleep(0.5) 
            self.signals.ask_confirmation.emit(
                "Confirm Detailed Submit", 
                f"Please review the DETAILED feedback for:\n{c_name}\n\nAre you ready to SUBMIT?"
            )
            self.wait_event.clear()
            self.wait_event.wait()
            
            if self.user_confirmed:
                if (el := self.check_element("_ctl0_ContentPlaceHolder1_cmdSubmit")):
                    el.click()
                    self.signals.status.emit("notify", "Submitted Detailed form. Waiting for refresh...")
                    time.sleep(1.5)
            else:
                self.signals.status.emit("error", f"Skipped Submit for {c_name}")
                
            self.signals.ask_confirmation.emit(
                "Confirm Reset", 
                "Do you want to click RESET to prepare for the next course?"
            )
            self.wait_event.clear()
            self.wait_event.wait()

            if self.user_confirmed:
                if (el := self.check_element("_ctl0_ContentPlaceHolder1_cmdReset")):
                    try:
                        el.click()
                        time.sleep(1.5)
                    except Exception:
                        pass
            else:
                 self.signals.status.emit("error", f"Skipped Reset for {c_name}")

        self.signals.status.emit("success", "Detailed feedback completed")


class App(QtWidgets.QMainWindow):
    def __init__(self):
        super(App, self).__init__()
        
        # UI Loaded dynamically via PyInstaller-safe resource path!
        uic.loadUi(resource_path('mainwindow.ui'), self)
        
        self.stackedWidget.setCurrentWidget(self.page)
        self.feedButton.setEnabled(False)
        self.comboBox.setEnabled(False)
        
        self.actionRandom_Gen.setCheckable(True)
        self.actionManual_Input.setCheckable(True)
        self.actionRandom_Gen.setChecked(True)

        self.actionRandom_Gen.toggled.connect(self.on_random_toggled)
        self.actionManual_Input.toggled.connect(self.on_manual_toggled)
        self.actionExit.triggered.connect(self.close)
        
        self.feedButton.clicked.connect(self.start_autofeed)
        self.pushButton.clicked.connect(self.on_contributor_selected)
        self.mi_pushButton.clicked.connect(self.on_manual_submit)
        
        self.worker = SeleniumWorker()
        self.worker.signals.status.connect(self.update_status)
        self.worker.signals.progress.connect(self.progressBar.setValue)
        self.worker.signals.departments_ready.connect(self.populate_departments)
        self.worker.signals.ask_contributor.connect(self.prompt_contributor)
        self.worker.signals.ask_manual_input.connect(self.prompt_manual)
        self.worker.signals.ask_confirmation.connect(self.prompt_confirmation)
        self.worker.signals.feed_finished.connect(lambda: self.feedButton.setEnabled(True))
        
        self.worker.mode = "init"
        self.worker.start()

    def on_random_toggled(self, checked):
        if checked: self.actionManual_Input.setChecked(False)
        else: self.actionManual_Input.setChecked(True)

    def on_manual_toggled(self, checked):
        if checked: self.actionRandom_Gen.setChecked(False)
        else: self.actionRandom_Gen.setChecked(True)

    @QtCore.pyqtSlot(str, str)
    def update_status(self, msg_type, msg):
        colors = {"notify": "#000000", "error": "#A11515", "success": "#33AA33", "special": "#3a9fbf"}
        self.progressLabel.setStyleSheet(f"color: {colors.get(msg_type, '#000000')}; font-weight: bold;")
        self.progressLabel.setText(msg)

    @QtCore.pyqtSlot(list)
    def populate_departments(self, depts):
        self.comboBox.clear()
        self.comboBox.addItems(depts)
        self.comboBox.setEnabled(True)
        self.feedButton.setEnabled(True)
        self.update_status("success", "Select your department")

    def start_autofeed(self):
        if self.comboBox.currentIndex() == 0:
            self.update_status("error", "You must select a department")
            return
        if not self.regNo.text() or not self.access_code.text():
            self.update_status("error", "Reg No and Access Code cannot be empty")
            return
            
        self.feedButton.setEnabled(False)
        
        self.worker.reg_no = self.regNo.text()
        self.worker.access_code = self.access_code.text()
        self.worker.dept_index = self.comboBox.currentIndex()
        self.worker.is_regular = self.checkBox.isChecked()
        self.worker.is_detailed = self.checkBox_2.isChecked()
        self.worker.is_manual = self.actionManual_Input.isChecked()
        
        self.worker.mode = "feed"
        self.worker.start()

    @QtCore.pyqtSlot(str, list)
    def prompt_contributor(self, course_name, contributors):
        self.label.setText(f"Course ({course_name}) has multiple contributors. Select one:")
        self.listWidget.clear()
        self.listWidget.addItems(contributors)
        self.listWidget.setCurrentRow(0)
        self.stackedWidget.setCurrentWidget(self.page_2)

    def on_contributor_selected(self):
        self.worker.selected_idx = self.listWidget.currentRow()
        self.stackedWidget.setCurrentWidget(self.page)
        self.worker.wait_event.set()

    @QtCore.pyqtSlot(str, str)
    def prompt_manual(self, course_name, teacher):
        self.mi_label.setText(f"Enter your feedback for {course_name} - {teacher}")
        self.stackedWidget.setCurrentWidget(self.page_3)

    def on_manual_submit(self):
        self.worker.manual_val = self.mi_spinBox.value()
        self.stackedWidget.setCurrentWidget(self.page)
        self.worker.wait_event.set()

    @QtCore.pyqtSlot(str, str)
    def prompt_confirmation(self, title, message):
        self.activateWindow()
        reply = QtWidgets.QMessageBox.question(
            self, title, message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes
        )
        self.worker.user_confirmed = (reply == QtWidgets.QMessageBox.Yes)
        self.worker.wait_event.set()

    def closeEvent(self, event):
        if self.worker.browser:
            self.worker.browser.quit()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = App()
    window.show()
    sys.exit(app.exec_())