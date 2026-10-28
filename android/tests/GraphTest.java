package com.dsefa.flir;
public final class GraphTest {
    static void check(boolean b,String m){if(!b)throw new AssertionError(m);}
    public static void main(String[] a){
        GraphModel g=new GraphModel();double[] original={25.6};g.add(100000,original);original[0]=0;
        g.pause(true);g.add(110000,new double[]{26.2});
        check(g.end()==100000,"pause freezes viewport, not measurement storage");
        check(g.nearest(110000).values[0]==26.2,"paused graph collects new values");
        check(g.nearest(100000).values[0]==25.6,"sample cannot alias mutable caller data");
        g.live();check(g.end()==110000,"live returns to latest without gap");
        g.zoom(.01);check(g.window()==5000,"zoom lower bound");
        g.zoom(100000);check(g.window()==3600000,"zoom upper bound");
        g.pan(-1000);check(g.end()==100000&&g.paused(),"pan clamps to first timestamp and pauses viewport");
        check(GraphModel.age(61440000).equals("17h 4m 0s ago"),"exact requested age format");
        g.add(500,new double[]{20});check(g.samples().size()==1,"replay rewind clears old timeline");
        g.clear();check(g.nearest(1)==null&&g.samples().isEmpty(),"reset clears crosshair source");
        System.out.println("PASS graph pause / continuous collection / zoom / pan / age / rewind");
    }
}
