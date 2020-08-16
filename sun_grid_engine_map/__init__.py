import pickle
import os
import stat
import subprocess
import qstat
import time
import shutil
import tempfile
import json


def _make_worker_node_script(module_name, function_name, environ):
    add_environ = ""
    for key in environ:
        add_environ += 'os.environ["{key:s}"] = "{value:s}"\n'.format(
            key=key.encode("unicode_escape").decode(),
            value=environ[key].encode("unicode_escape").decode(),
        )

    return (
        ""
        "# Generated by sun_grid_engine_map.\n"
        "# Do not modify.\n"
        "from {module_name:s} import {function_name:s}\n"
        "import pickle\n"
        "import sys\n"
        "import os\n"
        "\n"
        "{add_environ:s}"
        "\n"
        "assert(len(sys.argv) == 2)\n"
        'with open(sys.argv[1], "rb") as f:\n'
        "    job = pickle.loads(f.read())\n"
        "\n"
        "return_value = {function_name:s}(job)\n"
        "\n"
        'with open(sys.argv[1]+".out", "wb") as f:\n'
        "    f.write(pickle.dumps(return_value))\n"
        "".format(
            module_name=module_name,
            function_name=function_name,
            add_environ=add_environ,
        )
    )


def _qsub(
    qsub_path,
    queue_name,
    script_exe_path,
    script_path,
    arguments,
    JB_name,
    stdout_path,
    stderr_path,
):
    cmd = [qsub_path]
    if queue_name:
        cmd += ["-q", queue_name]
    cmd += [
        "-o",
        stdout_path,
    ]
    cmd += [
        "-e",
        stderr_path,
    ]
    cmd += [
        "-N",
        JB_name,
    ]
    cmd += [
        "-V",
    ]  # export enivronment variables to worker node
    cmd += [
        "-S",
        script_exe_path,
    ]
    cmd += [script_path]
    for argument in arguments:
        cmd += [argument]

    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        print("returncode", e.returncode)
        print("output", e.output)
        raise


def _local_sub(
    qsub_path,
    queue_name,
    script_exe_path,
    script_path,
    arguments,
    JB_name,
    stdout_path,
    stderr_path,
):
    cmd = [script_exe_path, script_path]
    for argument in arguments:
        cmd += [argument]
    with open(stdout_path, "w") as fstdout:
        with open(stderr_path, "w") as fstderr:
            subprocess.call(cmd, stdout=fstdout, stderr=fstderr)


def _job_path(work_dir, idx):
    return os.path.abspath(os.path.join(work_dir, "{:09d}.pkl".format(idx)))


def _session_id_from_time_now():
    # This must be a valid filename.
    return time.strftime("%Y-%m-%d_%H-%M-%S", time.gmtime())


def _times_iso8601():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


def _log(msg, flavor="msg"):
    print(
        '{{"time": "{:s}", "{:s}": "{:s}"}}'.format(
            _times_iso8601(), flavor, msg,
        )
    )


def _make_JB_name(session_id, idx):
    return "q{:s}#{:09d}".format(session_id, idx)


def _idx_from_JB_name(JB_name):
    idx_str = JB_name.split("#")[1]
    return int(idx_str)


def _has_non_zero_stderrs(work_dir, num_jobs):
    has_errors = False
    for idx in range(num_jobs):
        e_path = _job_path(work_dir, idx) + ".e"
        if os.stat(e_path).st_size != 0:
            has_errors = True
    return has_errors


def __qdel(JB_job_number, qdel_path):
    try:
        _ = subprocess.check_output(
            [qdel_path, str(JB_job_number)], stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError as e:
        _log("qdel returncode: {:s}".format(e.returncode), flavor="error")
        _log("qdel stdout: {:s}".format(e.output), flavor="error")
        raise


def _qdel(JB_job_number, qdel_path):
    while True:
        try:
            __qdel(JB_job_number, qdel_path)
            break
        except KeyboardInterrupt:
            raise
        except Exception as bad:
            print(bad)
            time.sleep(1)


def _qstat(qstat_path):
    """
    Return lists of running and pending jobs.
    Try again in case of Failure.
    Only except KeyboardInterrupt to stop.
    """
    while True:
        try:
            running, pending = qstat.qstat(qstat_path=qstat_path)
            break
        except KeyboardInterrupt:
            raise
        except Exception as bad:
            _log("Problem in qstat", flavor="error")
            print(bad)
            time.sleep(1)
    return running, pending


def _filter_jobs_by_JB_name(jobs, JB_names_set):
    my_jobs = []
    for job in jobs:
        if job["JB_name"] in JB_names_set:
            my_jobs.append(job)
    return my_jobs


def _extract_error_from_running_pending(
    jobs_running, jobs_pending, error_state_indicator
):
    # split into runnning, pending, and error
    _running = []
    _pending = []
    _error = []

    for job in jobs_running:
        if error_state_indicator in job["state"]:
            _error.append(job)
        else:
            _running.append(job)

    for job in jobs_pending:
        if error_state_indicator in job["state"]:
            _error.append(job)
        else:
            _pending.append(job)

    return _running, _pending, _error


def _jobs_running_pending_error(
    JB_names_set, error_state_indicator, qstat_path
):
    all_jobs_running, all_jobs_pending = _qstat(qstat_path=qstat_path)
    jobs_running = _filter_jobs_by_JB_name(all_jobs_running, JB_names_set)
    jobs_pending = _filter_jobs_by_JB_name(all_jobs_pending, JB_names_set)
    return _extract_error_from_running_pending(
        jobs_running=jobs_running,
        jobs_pending=jobs_pending,
        error_state_indicator=error_state_indicator,
    )


def map(
    function,
    jobs,
    queue_name=None,
    python_path=os.path.abspath(shutil.which("python")),
    polling_interval_qstat=5,
    verbose=True,
    work_dir=None,
    keep_work_dir=False,
    max_num_resubmissions=10,
    qsub_path="qsub",
    qstat_path="qstat",
    qdel_path="qdel",
    error_state_indicator="E",
):
    """
    Maps jobs to a function for embarrassingly parallel processing on a qsub
    computing-cluster.

    This for loop:

    >    results = []
    >    for job in jobs:
    >        results.append(function(job))

    will be executed in parallel on a qsub computing-cluster in order to obtain
    results.
    Both the jobs and results must be serializable using pickle.
    The function must be part of an installed python-module.

    If qsub is not installed, map falls back to serial processing on the local
    machine. This allows testing on machines without qsub.

    Parameters
    ----------
    function : function-pointer
        Pointer to a function in a python module. It must have both:
        function.__module__
        function.__name__
    jobs : list
        List of jobs. A job in the list must be a valid input to function.
    queue_name : string, optional
        Name of the queue to submit jobs to.
    python_path : string, optional
        The python path to be used on the computing-cluster's worker-nodes to
        execute the worker-node's python-script.
    polling_interval_qstat : float, optional
        The time in seconds to wait before polling qstat again while waiting
        for the jobs to finish.
    verbose : bool, optional
        Print to stdout.
    work_dir : string, optional
        The directory path where the jobs, the results and the
        worker-node-script is stored.
    keep_work_dir : bool, optional
        When True, the working directory will not be removed.
    max_num_resubmissions: int, optional
        In case of error-state in job, the job will be tried this often to be
        resubmitted befor giving up on it.

    Example
    -------
    results = map(
        function=numpy.sum,
        jobs=[numpy.arange(i, 100+i) for i in range(10)])
    """
    session_id = _session_id_from_time_now()
    if work_dir is None:
        work_dir = os.path.abspath(os.path.join(".", ".qsub_" + session_id))

    if os.path.exists(qsub_path):
        QSUB = True
    else:
        QSUB = shutil.which(qsub_path) is not None

    if verbose:
        _log("Start map().")
        if QSUB:
            _log("Using {:s}.".format(qsub_path))
        else:
            _log("No {:s}. Falling back to serial.".format(qsub_path))

    os.makedirs(work_dir)
    if verbose:
        _log("Tmp dir {:s}".format(work_dir))

    if verbose:
        _log("Write worker node script.")

    script_str = _make_worker_node_script(
        module_name=function.__module__,
        function_name=function.__name__,
        environ=dict(os.environ),
    )
    script_path = os.path.join(work_dir, "worker_node_script.py")
    with open(script_path, "wt") as f:
        f.write(script_str)
    st = os.stat(script_path)
    os.chmod(script_path, st.st_mode | stat.S_IEXEC)

    if verbose:
        _log("Write jobs.")
    JB_names_in_session = []
    for idx, job in enumerate(jobs):
        JB_name = _make_JB_name(session_id=session_id, idx=idx)
        JB_names_in_session.append(JB_name)
        with open(_job_path(work_dir, idx), "wb") as f:
            f.write(pickle.dumps(job))

    if verbose:
        _log("Submitt jobs.")

    if QSUB:
        submitter = _qsub
    else:
        submitter = _local_sub

    for JB_name in JB_names_in_session:
        idx = _idx_from_JB_name(JB_name)
        submitter(
            qsub_path=qsub_path,
            queue_name=queue_name,
            script_exe_path=python_path,
            script_path=script_path,
            arguments=[_job_path(work_dir, idx)],
            JB_name=JB_name,
            stdout_path=_job_path(work_dir, idx) + ".o",
            stderr_path=_job_path(work_dir, idx) + ".e",
        )

    if verbose:
        _log("Wait for jobs to finish.")

    if QSUB:
        JB_names_in_session_set = set(JB_names_in_session)
        still_running = True
        num_resubmissions_by_idx = {}
        while still_running:
            (
                jobs_running,
                jobs_pending,
                jobs_error,
            ) = _jobs_running_pending_error(
                JB_names_set=JB_names_in_session_set,
                error_state_indicator=error_state_indicator,
                qstat_path=qstat_path,
            )
            num_running = len(jobs_running)
            num_pending = len(jobs_pending)
            num_error = len(jobs_error)
            num_lost = 0
            for idx in num_resubmissions_by_idx:
                if num_resubmissions_by_idx[idx] >= max_num_resubmissions:
                    num_lost += 1

            if verbose:
                _log(
                    "{: 4d} running, {: 4d} pending, {: 4d} error, {: 4d} lost".format(
                        num_running, num_pending, num_error, num_lost,
                    )
                )

            for job in jobs_error:
                idx = _idx_from_JB_name(job["JB_name"])
                if idx in num_resubmissions_by_idx:
                    num_resubmissions_by_idx[idx] += 1
                else:
                    num_resubmissions_by_idx[idx] = 0

                _log(
                    "JB_name {:s}, JB_job_number {:s}, idx {:09d}".format(
                        job["JB_name"], job["JB_job_number"], idx
                    ),
                    flavor="error",
                )
                _log("qdel JB_job_number {:s}".format(job["JB_job_number"]))
                _qdel(
                    JB_job_number=job["JB_job_number"], qdel_path=qdel_path,
                )

                if num_resubmissions_by_idx[idx] < max_num_resubmissions:
                    _log(
                        "resubmit {:d} of {:d}, JB_name {:s}".format(
                            num_resubmissions_by_idx[idx] + 1,
                            max_num_resubmissions,
                            job["JB_name"],
                        )
                    )
                    submitter(
                        qsub_path=qsub_path,
                        queue_name=queue_name,
                        script_exe_path=python_path,
                        script_path=script_path,
                        arguments=[_job_path(work_dir, idx)],
                        JB_name=job["JB_name"],
                        stdout_path=_job_path(work_dir, idx) + ".o",
                        stderr_path=_job_path(work_dir, idx) + ".e",
                    )

            if jobs_error:
                resup = os.path.join(work_dir, "num_resubmissions_by_idx.json")
                with open(resup, "wt") as f:
                    f.write(json.dumps(num_resubmissions_by_idx, indent=4))

            if num_running == 0 and num_pending == 0:
                still_running = False

            time.sleep(polling_interval_qstat)

    if verbose:
        _log("Collect results.")

    results = []
    for idx, job in enumerate(jobs):
        try:
            result_path = _job_path(work_dir, idx) + ".out"
            with open(result_path, "rb") as f:
                result = pickle.loads(f.read())
            results.append(result)
        except FileNotFoundError:
            _log("No result {:s}".format(result_path), flavor="error")
            results.append(None)

    if (
        _has_non_zero_stderrs(work_dir=work_dir, num_jobs=len(jobs))
        or keep_work_dir
    ):
        _log("Found stderr.", flavor="error")
        _log("Keep work dir: {:s}".format(work_dir))
    else:
        shutil.rmtree(work_dir)

    if verbose:
        _log("Stop map().")

    return results
