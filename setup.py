from distutils.core import setup

setup(
    name='sun_grid_engine_map',
    version='0.0.2',
    description='Map and reduce for qsub.',
    url='https://github.com/cherenkov-plenoscope/sun_grid_engine_map',
    author='Sebastian Achim Mueller',
    author_email='sebastian-achim.mueller@mpi-hd.mpg.de',
    license='MIT',
    packages=[
        'sun_grid_engine_map',
    ],
    install_requires=[
        'qstat',
    ],
    zip_safe=False,
)
