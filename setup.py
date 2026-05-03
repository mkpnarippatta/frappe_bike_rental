from setuptools import setup, find_packages

with open("requirements.txt") as f:
    install_requires = f.read().strip().split("\n")

setup(
    name="bike_rental",
    version="0.0.1",
    description="Bike rental management system for multi-hub operators",
    author="Ali",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    python_requires=">=3.10",
    install_requires=install_requires,
)
