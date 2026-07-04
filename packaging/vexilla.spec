%global __brp_mangle_shebangs_exclude_from ^.%{_datadir}/.*$

Name:           vexilla
Version:        0.1.0
Release:        1%{?dist}
Summary:        See what your device is really talking to — in plain English
License:        MIT
URL:            https://github.com/vexx/vexilla
Source0:        %{pypi_source vexilla}
BuildArch:      noarch
BuildRequires:  python3-devel python3-setuptools
Requires:       python3 >= 3.11
Requires:       python3-fastapi python3-uvicorn python3-jinja2
Requires:       python3-typer python3-pydantic python3-pydantic-settings
Requires:       python3-multipart

%description
Vexilla is a lightweight, privacy-first Linux agent that watches which
applications use the internet, which external services and domains they
connect to, how much data they consume, and whether that behavior is
normal — then explains it all in plain human language.

Vexilla is NOT an antivirus and NOT a firewall. It is a digital
transparency companion for normal people.

%prep
%autosetup -n vexilla-%{version}
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
install -D -m 0644 packaging/vexilla.service %{buildroot}%{_unitdir}/vexilla.service
install -D -m 0644 data/kb.db %{buildroot}%{_datadir}/vexilla/kb.db
install -D -m 0644 packaging/config.toml.example %{buildroot}%{_sysconfdir}/vexilla/config.toml

%post
%systemd_post vexilla.service
# Create vexilla user
getent passwd vexilla >/dev/null 2>&1 || \
    useradd --system --no-create-home --shell /sbin/nologin vexilla

%preun
%systemd_preun vexilla.service

%postun
%systemd_postun_with_restart vexilla.service

%files
%{_bindir}/vexilla
%{_datadir}/vexilla/kb.db
%{python3_sitelib}/vexilla*
%{_unitdir}/vexilla.service
%config(noreplace) %{_sysconfdir}/vexilla/config.toml

%changelog
* Thu Jul 03 2026 Vexilla contributors <vexilla-dev@example.com> - 0.1.0-1
- Initial package
