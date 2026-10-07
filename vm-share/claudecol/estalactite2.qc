$modelname "claudecol/estalactite2.mdl"
$staticprop
$surfaceprop "rock"
$cdmaterials "models/claudecol/"
$body "body" "estalactite2_phys.smd"
$sequence "idle" "estalactite2_phys.smd"
$collisionmodel "estalactite2_phys.smd"
{
	$concave
	$maxconvexpieces 64
	$mass 1000
}
