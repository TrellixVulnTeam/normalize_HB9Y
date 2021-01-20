import setuptools

setuptools.setup(
    name='normalize',
    version='0.1.0',
    description='Raster and vector files normalization service',
    author='Kyriakos Psarakis',
    author_email='kpsarakis94@gmail.com',
    license='MIT',
    packages=setuptools.find_packages(exclude=('tests*',)),
    install_requires=[
        # moved to requirements.txt
    ],
    package_data={'normalize': [
        'logging.conf', 'schema.sql'
    ]},
    python_requires='>=3.7',
    zip_safe=False,
)
