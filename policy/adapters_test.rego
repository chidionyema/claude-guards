package adapters_test

import rego.v1

import data.adapters

test_session_start_names_seven_adapters if {
	count(adapters.session_start) == 7
}

test_no_session_start_adapter_lives_in_the_archive if {
	every row in adapters.session_start {
		not contains(row[0], "archive/")
	}
}

test_every_adapter_is_a_bare_python_file_name if {
	every row in adapters.session_start {
		endswith(row[0], ".py")
		not contains(row[0], "/")
	}
}
