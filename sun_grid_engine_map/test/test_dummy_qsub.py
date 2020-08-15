import sun_grid_engine_map as qmr
import numpy as np
import tempfile
import os
import pkg_resources

def _tmp_path(name):
    return pkg_resources.resource_filename(
        'sun_grid_engine_map',
        os.path.join('test', 'resources', name)
    )

tmp_state_path = _tmp_path('tmp_qsub.json')
qsub_path = _tmp_path('dummy_qsub.py')
qstat_path = _tmp_path('dummy_qstat.py')
qdel_path = _tmp_path('dummy_qdel.py')


def test_dummys_exist():
    assert os.path.exists(qsub_path)
    assert os.path.exists(qstat_path)
    assert os.path.exists(qdel_path)


def test_run():

    with tempfile.TemporaryDirectory(prefix='sge') as tmp_dir:
        tmp_dir = "runp"
        os.makedirs(tmp_dir, exist_ok=True)
        qsub_tmp_dir = os.path.join(tmp_dir, "qsub_tmp")

        if os.path.exists(tmp_state_path):
            os.remove(tmp_state_path)

        NUM_JOBS = 30

        jobs = []
        for i in range(NUM_JOBS):
            job = np.arange(0, 100)
            jobs.append(job)

        results = qmr.map(
            function=np.sum,
            jobs=jobs,
            polling_interval_qstat=.1,
            work_dir=qsub_tmp_dir,
            keep_work_dir=True,
            max_num_resubmissions=10,
            qsub_path=qsub_path,
            qstat_path=qstat_path,
            qdel_path=qdel_path,
            error_state_indicator='E',
        )
