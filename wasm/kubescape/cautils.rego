# Kubescape's always-loaded Rego helper library, verbatim from
# github.com/kubescape/opa-utils v0.0.315 resources/dependencies.go (RegoCAUtils), Apache-2.0.
package cautils
import rego.v1

list_contains(lista,element) if {
  some i
  lista[i] == element
}

# getPodName(metadata) = name {
# 	name := metadata.generateName
#}
getPodName(metadata) = name if {
    name := metadata.name
}

#returns subobject ,sub1 is partial to parent,  e.g parent = {a:a,b:b,c:c,d:d}
# sub1 = {b:b,c:c} - result is {b:b,c:c}, if sub1={b:b,e:f} returns {b:b}
object_intersection(parent,sub1) = r if {

  r := {k:p  | p := sub1[k]
              parent[k]== p
              }
}

#returns if parent contains sub(both are objects not sets!!)
is_subobject(sub,parent) if {
object_intersection(sub,parent)  == sub
}

# parse unix permissions
unix_permission(perm) = ret if {
    ret := {
        "user": unix_permission_from_octal(bits.rsh(perm, 6)), 
        "group": unix_permission_from_octal(bits.rsh(perm, 3)),
        "everyone": unix_permission_from_octal(perm),
        "setuid": bits.and(perm, 2048) != 0,
        "setgid": bits.and(perm, 1024) != 0,
        "sticky": bits.and(perm, 512) != 0
    }
}

# parse single unix permission (one octal digit)
unix_permission_from_octal(perm) = ret if {
    ret := {
        "exec": bits.and(perm, 1) != 0,
        "write": bits.and(perm, 2) != 0,
        "read": bits.and(perm, 4) != 0
    }
}

# check that the given permissions are more permissive than 644
is_not_strict_conf_permission(p) if {
    not is_strict_conf_permission(p)
}

# check that the given permissions are 644 or above
# deprecated. use 'unix_permissions_allow' instead
is_strict_conf_permission(p) if {
    perm := unix_permission(p)
    not perm.user.exec
    not perm.group.write
    not perm.group.exec
    not perm.everyone.write
    not perm.everyone.exec
    not perm.setgid
    not perm.setuid
    not perm.sticky
}

# check if (unix permission integers) 'actual' permissions allowed by 'allow'
unix_permissions_allow(allow, actual) if {
    allow_parsed := unix_permission(allow)
    actual_parsed := unix_permission(actual)
    
    # attributes    
    _unix_perm_allow(allow_parsed.setuid,  actual_parsed.setuid)
    _unix_perm_allow(allow_parsed.setgid,  actual_parsed.setgid)
    _unix_perm_allow(allow_parsed.sticky,  actual_parsed.sticky)
    
    # regular    
    keys :=  ["read", "write", "exec"]
	count({key | key := keys[_]; not _unix_perm_allow(allow_parsed.user[key],  actual_parsed.user[key])}) == 0
	count({key | key := keys[_]; not _unix_perm_allow(allow_parsed.group[key],  actual_parsed.group[key])}) == 0
	count({key | key := keys[_]; not _unix_perm_allow(allow_parsed.everyone[key],  actual_parsed.everyone[key])}) == 0
}

# check if boolian 'actual' permission allowed by 'allow'
# true, true => true
# true, false => true
# false, false => ture
# false, true => false
_unix_perm_allow(allow, actual) if {
    allow == true
}
_unix_perm_allow(allow, actual) if {
    allow == actual
}

# Check if file ownership is different than root:root
is_not_strict_conf_ownership(ownership) if {
    not is_strict_conf_ownership(ownership)
}

# File ownership check only if there is no error
is_strict_conf_ownership(ownership) if {
    ownership.err
}

# Ensure file ownership are root:root
is_strict_conf_ownership(ownership) if {
    ownership.uid == 0
    ownership.gid == 0
}
