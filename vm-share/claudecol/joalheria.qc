$modelname "claudecol/joalheria.mdl"
$staticprop
$surfaceprop "plastic"
$cdmaterials "models/claudecol/"
$body "body" "joalheria_phys.smd"
$sequence "idle" "joalheria_phys.smd"
$collisionmodel "joalheria_phys.smd"
{
	$concave
	$maxconvexpieces 64
	$mass 1000
}
