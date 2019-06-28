import pickle
import os
import stat
import subprocess
import qstat
import time
import shutil
import tempfile


def __make_worker_node_script(module_name, function_name):
    return '' \
        '# Generated by sun_grid_engine_map.\n' \
        '# Do not modify.\n' \
        'from {module_name:s} import {function_name:s}\n' \
        'import pickle\n' \
        'import sys\n' \
        '\n' \
        '\n' \
        'assert(len(sys.argv) == 2)\n' \
        'with open(sys.argv[1], "rb") as f:\n' \
        '    job = pickle.loads(f.read())\n' \
        '\n' \
        'return_value = {function_name:s}(job)\n' \
        '\n' \
        'with open(sys.argv[1]+".out", "wb") as f:\n' \
        '    f.write(pickle.dumps(return_value))\n' \
        ''.format(
            module_name=module_name,
            function_name=function_name)


def __qsub(
    script_exe_path,
    script_path,
    arguments,
    job_name,
    stdout_path,
    stderr_path,
    queue_name=None,
):
    cmd = ['qsub']
    if queue_name:
        cmd += ['-q', queue_name]
    cmd += ['-o', stdout_path, ]
    cmd += ['-e', stderr_path, ]
    cmd += ['-N', job_name, ]
    cmd += ['-V', ]  # export enivronment variables to worker node
    cmd += ['-S', script_exe_path, ]
    cmd += [script_path]
    for argument in arguments:
        cmd += [argument]

    try:
        subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        print('returncode', e.returncode)
        print('output', e.output)
        raise


def __local_sub(
    script_exe_path,
    script_path,
    arguments,
    job_name,
    stdout_path,
    stderr_path,
    queue_name=None,
):
    cmd = [
        script_exe_path,
        script_path]
    for argument in arguments:
        cmd += [argument]
    with open(stdout_path, 'w') as fstdout:
        with open(stderr_path, 'w') as fstderr:
            subprocess.call(
                cmd,
                stdout=fstdout,
                stderr=fstderr)


def __job_path(tmp_dir, idx):
    return os.path.abspath(
        os.path.join(tmp_dir, "{:09d}.pkl".format(idx)))


def __timestamp():
    return time.strftime("%Y%m%d%H%M%S", time.gmtime())


def __human_timestamp():
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def __print_template(msg):
    return "[Qsub Map and Reduce: {:s}]".format(msg)


def __make_job_name(timestamp, idx):
    return "q{:s}.{:09d}".format(timestamp, idx)


def __has_non_zero_stderrs(tmp_dir, num_jobs):
    has_errors = False
    for idx in range(num_jobs):
        e_path = __job_path(tmp_dir, idx)+'.e'
        if os.stat(e_path).st_size != 0:
            has_errors = True
    return has_errors


def __num_jobs_running_and_pending(job_names_set):
    running, pending = qstat.qstat()
    num_running = 0
    num_pending = 0
    for j in running:
        if j['JB_name'] in job_names_set:
            num_running += 1
    for j in pending:
        if j['JB_name'] in job_names_set:
            num_pending += 1
    return num_running, num_pending


def map(
    function,
    jobs,
    queue_name=None,
    python_path=os.path.abspath(shutil.which('python')),
    polling_interval_qstat=5,
    verbose=True,
    dump_path=os.path.abspath(os.path.join('.', 'qsub_dumb')),
    force_dump=False,
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
    dump_path : string, optional
        A path to dump the working directory to, in case of errors.
        Helps with debugging.
    force_dump : bool, optional
        When True, the working directory will be dumped in any case to
        dump_path.

    Example
    -------
    results = map(
        function=numpy.sum,
        jobs=[numpy.arange(i, 100+i) for i in range(10)])
    """
    timestamp = __timestamp()
    QSUB = shutil.which('qsub') is not None

    if verbose:
        print(__print_template("Start: {:s}".format(__human_timestamp())))
        if QSUB:
            print(__print_template("Using qsub."))
        else:
            print(__print_template("No qsub. Falling back to serial."))

    with tempfile.TemporaryDirectory(prefix='qsub_map_reduce') as tmp_dir:
        if verbose:
            print(__print_template("Tmp dir {:s}".format(tmp_dir)))

        if verbose:
            print(__print_template("Write jobs."))
        for idx, job in enumerate(jobs):
            with open(__job_path(tmp_dir, idx), 'wb') as f:
                f.write(pickle.dumps(job))

        if verbose:
            print(__print_template("Write worker node script."))
        script_str = __make_worker_node_script(
            module_name=function.__module__,
            function_name=function.__name__)
        script_path = os.path.join(tmp_dir, 'worker_node_script.py')
        with open(script_path, "wt") as f:
            f.write(script_str)
        st = os.stat(script_path)
        os.chmod(script_path, st.st_mode | stat.S_IEXEC)

        if QSUB:
            submitt = __qsub
        else:
            submitt = __local_sub

        if verbose:
            print(__print_template("Submitt jobs."))
        job_names = []
        for idx in range(len(jobs)):
            job_names.append(__make_job_name(timestamp=timestamp, idx=idx))
            submitt(
                script_exe_path=python_path,
                script_path=script_path,
                arguments=[__job_path(tmp_dir, idx)],
                job_name=job_names[-1],
                queue_name=queue_name,
                stdout_path=__job_path(tmp_dir, idx)+'.o',
                stderr_path=__job_path(tmp_dir, idx)+'.e',)

        if verbose:
            print(__print_template("Wait for jobs to finish."))
        if QSUB:
            job_names_set = set(job_names)
            still_running = True
            while still_running:
                num_running, num_pending = __num_jobs_running_and_pending(
                    job_names_set=job_names_set)
                if num_running == 0 and num_pending == 0:
                    still_running = False
                if verbose:
                    print(
                        __print_template(
                            "{:d} running, {:d}".format(
                                num_running,
                                num_pending)))
                time.sleep(polling_interval_qstat)

        if verbose:
            print(__print_template("Collect results."))
        results = []
        for idx, job in enumerate(jobs):
            try:
                result_path = __job_path(tmp_dir, idx)+'.out'
                with open(result_path, "rb") as f:
                    result = pickle.loads(f.read())
                results.append(result)
            except FileNotFoundError:
                print(__print_template(
                    "ERROR. No result {:s}".format(result_path)))
                results.append(None)

        if (
            __has_non_zero_stderrs(tmp_dir=tmp_dir, num_jobs=len(jobs)) or
            force_dump
        ):
            print(__print_template("Found stderr."))
            print(__print_template("Dumping to: {:s}".format(dump_path)))
            shutil.copytree(tmp_dir, dump_path)

    if verbose:
        print(__print_template("Stop: {:s}".format(__human_timestamp())))

    return results
