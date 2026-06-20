( BEGIN FILE BackRoundover-PT5-04-back.ncTNUM: -1 )
( Lefty:False Nunits:1 )
( cline: 9.733 delta:15.5 )
( start_unit: 1 num_units: 1)
( MOP:  BackRoundover-PT5-04-back )
( FILE: G:\Shared drives\AlloyProjectFiles\Customer CAD files\Alloy-Standard-Builds-CAM\s-in\FullStandardS-Specific\BackRoundover-PT5-04-back.nc)
G90
(  BEGIN TOOL LIST )
(  TOOL 15 - Roundover PT125 Accusize - DESC: 0.2625 DIA, 2 FLUTE,  CARBIDE MAT )
(  ENDOF TOOL LIST )
( BackRoundover-PT5-04-back)
( Accusize 1011-0018 Depth .1822 diameter .2625 but added .001 since there was a line in test cuts)
T15
S9000
M3
G0 Z6.0000
G0 X11.3523 Y-7.4479 
G1 X11.3523 Y-7.4479 Z1.5778 F75.
G17
G2X11.0076Y-7.3690Z1.5778I-0.1329J0.2118 F25.
G2X10.9213Y-7.1536Z1.5778I0.5512J0.3458 F80.
G3X10.6090Y-6.8987Z1.5778I-0.3123J-0.0638
G1 X8.8232 Y-6.8987 Z1.5778
G3X8.5045Y-7.2128Z1.5778I0.0000J-0.3187
G1 X8.5025 Y-8.9841 Z1.5778
G2X8.4363Y-9.1348Z1.5778I-0.2049J0.0002
G2X8.0831Y-9.1200Z1.5778I-0.1692J0.1840 F75.
G0 Z6.0000
G0 X8.0831 Y-9.1200 
M5
G53 Z
G0 X2Y0
( END FILE BackRoundover-PT5-04-back.nc )
