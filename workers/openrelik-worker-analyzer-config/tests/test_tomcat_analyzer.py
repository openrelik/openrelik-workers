# Copyright 2024-2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Tomcat configuration analyzer tests."""

import textwrap
import unittest
from unittest.mock import mock_open, patch

from openrelik_worker_common.reporting import Priority, Report

from src.analyzers.tomcat_analyzer import analyze_config


class TomCatTests(unittest.TestCase):
    """Test the TomCat analyzer functions."""

    input_file = {"path": "/dummy/path"}

    def test_tomcat_access_log(self):
        """Test Tomcat access log."""

        # Arrange
        tomcat_access_log = """
        1.2.3.4 - - [12/Apr/2018:14:01:08 -0100] "GET /manager/html HTTP/1.1" 401 2001
        1.2.3.4 - admin [12/Apr/2018:14:01:09 -0100] "GET /manager/html HTTP/1.1" 200 22130
        1.2.3.4 - admin [12/Apr/2018:14:01:39 -0100] "POST /manager/html/upload?org.apache.catalina.filters.CSRF_NONCE=1ABCDEFGKLMONPQRSTIRQKD240384739 HTTP/1.1" 200 27809
        """

        report = textwrap.dedent("""
        * Tomcat Management: 1.2.3.4 - admin [12/Apr/2018:14:01:39 -0100] "POST /manager/html/upload?org.apache.catalina.filters.CSRF_NONCE=1ABCDEFGKLMONPQRSTIRQKD240384739 HTTP/1.1" 200 27809
        """).strip()

        summary = "Tomcat analysis found misconfigs"

        # Act
        with patch("builtins.open", mock_open(read_data=tomcat_access_log)):
            result = analyze_config(self.input_file, {})

        # Assert
        self.assertIsInstance(result, Report)
        self.assertEqual(result.priority, Priority.HIGH)
        self.assertEqual(result.summary, summary)
        self.assertEqual(result.to_markdown().strip(), report)

    def test_tomcat_app_deploy_log(self):
        """Test Tomcat for app deployment logs."""

        # Arrange
        tomcat_app_deploy_log = r"""
        21-Mar-2017 19:21:08.140 INFO [localhost-startStop-2] org.apache.catalina.startup.HostConfig.deployWAR Deploying web application archive C:\Program Files\Apache Software Foundation\Tomcat 9.0\webapps\MyAwesomeApp.war
        10-Sep-2012 11:41:12.283 INFO [localhost-startStop-1] org.apache.catalina.startup.HostConfig.deployWAR Deploying web application archive /opt/apache-tomcat-8.0.32/webapps/badboy.war
        """

        report = textwrap.dedent(r"""
        * Tomcat App Deployed: 21-Mar-2017 19:21:08.140 INFO [localhost-startStop-2] org.apache.catalina.startup.HostConfig.deployWAR Deploying web application archive C:\Program Files\Apache Software Foundation\Tomcat 9.0\webapps\MyAwesomeApp.war
        * Tomcat App Deployed: 10-Sep-2012 11:41:12.283 INFO [localhost-startStop-1] org.apache.catalina.startup.HostConfig.deployWAR Deploying web application archive /opt/apache-tomcat-8.0.32/webapps/badboy.war
        """).strip()
        summary = "Tomcat analysis found misconfigs"

        # Act
        with patch("builtins.open", mock_open(read_data=tomcat_app_deploy_log)):
            result = analyze_config(self.input_file, {})

        # Assert
        self.assertIsInstance(result, Report)
        self.assertEqual(result.priority, Priority.HIGH)
        self.assertEqual(result.summary, summary)
        self.assertEqual(result.to_markdown().strip(), report)

    def test_tomcat_password_file(self):
        """Test Tomcat password file."""

        # Arrange
        tomcat_password_file = """
        <?xml version='1.0' encoding='utf-8'?>
            <tomcat-users>
                <role rolename="tomcat"/>
                <role rolename="role1"/>
                <user username="tomcat" password="tomcat" roles="tomcat"/>
                <user username="both" password="tomcat" roles="tomcat,role1"/>
            </tomcat-users>
        """
        report = textwrap.dedent("""
        * tomcat user: <user username="tomcat" password="tomcat" roles="tomcat"/>
        * tomcat user: <user username="both" password="tomcat" roles="tomcat,role1"/>
        """).strip()
        summary = "Tomcat analysis found misconfigs"

        # Act
        with patch("builtins.open", mock_open(read_data=tomcat_password_file)):
            result = analyze_config(self.input_file, {})

        # Assert
        self.assertIsInstance(result, Report)
        self.assertEqual(result.priority, Priority.HIGH)
        self.assertEqual(result.summary, summary)
        self.assertEqual(result.to_markdown().strip(), report)

    def test_tomcat_servlet_readonly(self):
        """Test Tomcat servlet for read-only."""

        # Arrange
        tomcat_web_xml_file = """
        <?xml version='1.0' encoding='utf-8'?>
        <servlet>
            <servlet-name>default</servlet-name>
            <servlet-class>org.apache.catalina.servlets.DefaultServlet</servlet-class>
            <init-param>
                <param-name>readonly</param-name>
                <param-value>false</param-value>
            </init-param>
        </servlet>
        """
        report = textwrap.dedent("""
        * Tomcat servlet IS NOT read-only
        """).strip()
        summary = "Tomcat analysis found misconfigs"

        # Act
        with patch("builtins.open", mock_open(read_data=tomcat_web_xml_file)):
            result = analyze_config(self.input_file, {})

        # Assert
        self.assertIsInstance(result, Report)
        self.assertEqual(result.priority, Priority.HIGH)
        self.assertEqual(result.summary, summary)
        self.assertEqual(result.to_markdown().strip(), report)


if __name__ == "__main__":
    unittest.main()
